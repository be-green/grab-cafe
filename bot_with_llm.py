import discord
from discord.ext import tasks
from discord.ui import View, Button
import os
import asyncio
from database import init_database, get_unposted_postings, mark_posting_as_posted, format_posting_for_discord, refresh_aggregation_tables
from scraper import fetch_and_store_new_postings
from llm_interface import query_llm, get_last_sql_query, describe_query_results

class PaginatedDataView(View):
    def __init__(self, query_result, rows_per_page=5):
        super().__init__(timeout=300)  # 5 minute timeout
        self.query_result = query_result
        self.rows_per_page = rows_per_page
        self.current_page = 0
        self.total_pages = (len(query_result['rows']) + rows_per_page - 1) // rows_per_page

        # Disable buttons if only one page
        if self.total_pages <= 1:
            self.previous_button.disabled = True
            self.next_button.disabled = True

    def format_table_page(self):
        """Format current page as a table string"""
        start_idx = self.current_page * self.rows_per_page
        end_idx = min(start_idx + self.rows_per_page, len(self.query_result['rows']))

        columns = self.query_result['columns']
        page_rows = self.query_result['rows'][start_idx:end_idx]

        # Format data for table
        def format_value(val):
            if val is None:
                return "N/A"
            elif isinstance(val, float):
                return f"{val:.2f}"
            else:
                return str(val)

        # Calculate column widths (max 20 chars per column to prevent overflow)
        col_widths = {}
        for col in columns:
            col_widths[col] = min(len(col), 20)

        for row in page_rows:
            for col, val in zip(columns, row):
                formatted = format_value(val)
                col_widths[col] = min(max(col_widths[col], len(formatted)), 20)

        # Build table
        table_lines = []

        # Header
        header = " | ".join(col[:col_widths[col]].ljust(col_widths[col]) for col in columns)
        table_lines.append(header)
        table_lines.append("-" * len(header))

        # Rows
        for row in page_rows:
            formatted_vals = [format_value(val)[:col_widths[col]].ljust(col_widths[col]) for col, val in zip(columns, row)]
            row_str = " | ".join(formatted_vals)
            table_lines.append(row_str)

        return "```\n" + "\n".join(table_lines) + "\n```"

    def get_embed(self):
        """Just shows page controls, table sent separately"""
        embed = discord.Embed(
            title="",
            description=f"**Page {self.current_page + 1} of {self.total_pages}**",
            color=discord.Color.blue()
        )
        return embed

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.gray)
    async def previous_button(self, interaction: discord.Interaction, button: Button):
        if self.current_page > 0:
            self.current_page -= 1
            # Edit both the table message and embed
            await self.table_message.edit(content=self.format_table_page())
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.gray)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            # Edit both the table message and embed
            await self.table_message.edit(content=self.format_table_page())
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', '0'))
CHECK_INTERVAL_SECONDS = 60
ENABLE_LLM = 'true'
POST_LOOKBACK_DAYS = 1

class GradCafeBotWithLLM(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.llm_loaded = False
        self.processed_messages = set()

    async def setup_hook(self):
        if not self.check_gradcafe_task.is_running():
            self.check_gradcafe_task.start()

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print(f'Monitoring channel ID: {DISCORD_CHANNEL_ID}')
        print(f'Check interval: {CHECK_INTERVAL_SECONDS} seconds')
        print(f'LLM queries: {"Enabled" if ENABLE_LLM else "Disabled"}')
        print('------')

        if ENABLE_LLM and not self.llm_loaded:
            print("Initializing LLM client...")
            try:
                from llm_interface import get_llm
                await asyncio.to_thread(get_llm)
                self.llm_loaded = True
                print("LLM ready!")
            except Exception as e:
                print(f"Failed to load LLM: {e}")
                print("LLM queries will be disabled.")

    async def on_message(self, message):
        if message.author == self.user:
            return

        # Prevent processing the same message twice
        if message.id in self.processed_messages:
            return
        self.processed_messages.add(message.id)

        # Keep only last 100 message IDs to prevent memory growth
        if len(self.processed_messages) > 100:
            self.processed_messages = set(list(self.processed_messages)[-100:])

        if self.user.mentioned_in(message) and not message.mention_everyone:
            if not ENABLE_LLM or not self.llm_loaded:
                await message.channel.send("LLM queries are currently disabled.")
                return

            user_question = message.content.replace(f'<@{self.user.id}>', '').replace(f'<@!{self.user.id}>', '').strip()

            if not user_question:
                await message.channel.send("Hi! Ask me anything about economics graduate admissions data. For example: 'What month do most acceptances come out?' or 'Which schools send the most interviews?'")
                return

            # Check if user is requesting the last SQL query
            sql_request_keywords = ['show sql', 'last query', 'what was the query', 'show query', 'sql query', 'show the sql']
            if any(keyword in user_question.lower() for keyword in sql_request_keywords):
                sql_query, original_question = await asyncio.to_thread(get_last_sql_query)
                if sql_query:
                    response = f"Last query for: \"{original_question}\"\n\n```sql\n{sql_query}\n```"
                    await message.channel.send(response)
                else:
                    await message.channel.send("No SQL query has been run yet, or the last question didn't require a database query.")
                return

            try:
                recent_messages = []
                try:
                    # Fetch recent messages for context
                    async for recent_message in message.channel.history(limit=6, before=message, oldest_first=False):
                        content = recent_message.content.strip()
                        if content:
                            recent_messages.append({
                                "author": recent_message.author.display_name,
                                "content": content,
                                "is_bot": recent_message.author == self.user
                            })
                    # Reverse to get chronological order (oldest first)
                    recent_messages.reverse()
                except discord.HTTPException as e:
                    print(f"Failed to fetch recent channel context: {e}")

                # Beatriz responds directly
                response_text, query_result = await asyncio.to_thread(query_llm, user_question, recent_messages)

                # Handle query results
                if query_result and not query_result.get('error') and query_result.get('rows'):
                    row_count = len(query_result['rows'])

                    if row_count > 4:
                        # Too many rows - get Beatriz to describe the columns
                        response_text = await asyncio.to_thread(describe_query_results, user_question, query_result)

                        # Send response
                        if len(response_text) > 2000:
                            response_text = response_text[:1997] + "..."
                        await message.channel.send(response_text)

                        # Send table and paginated controls
                        view = PaginatedDataView(query_result, rows_per_page=5)
                        # Send table as regular message
                        table_msg = await message.channel.send(view.format_table_page())
                        view.table_message = table_msg
                        # Send embed with pagination buttons
                        await message.channel.send(embed=view.get_embed(), view=view)
                    else:
                        # 4 or fewer rows - just send Beatriz's summary, no table
                        if len(response_text) > 2000:
                            response_text = response_text[:1997] + "..."
                        await message.channel.send(response_text)
                else:
                    # No query results - just send text response
                    if len(response_text) > 2000:
                        response_text = response_text[:1997] + "..."
                    await message.channel.send(response_text)

            except Exception as e:
                await message.channel.send(f"Sorry, I encountered an error: {str(e)[:200]}")
                print(f"LLM query error: {e}")
                import traceback
                traceback.print_exc()

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def check_gradcafe_task(self):
        try:
            new_count = await asyncio.to_thread(fetch_and_store_new_postings)
            if new_count > 0:
                print(f"Found {new_count} new posting(s)")
                # Refresh aggregation tables for LLM when new data is added
                await asyncio.to_thread(refresh_aggregation_tables)
                print("Aggregation tables updated")

            unposted = await asyncio.to_thread(get_unposted_postings, POST_LOOKBACK_DAYS)

            if unposted:
                channel = self.get_channel(DISCORD_CHANNEL_ID)
                if not channel:
                    print(f"Error: Could not find channel with ID {DISCORD_CHANNEL_ID}")
                    return

                for posting in unposted:
                    try:
                        message = format_posting_for_discord(posting)
                        await channel.send(message)
                        await asyncio.to_thread(mark_posting_as_posted, posting['id'])
                        print(f"Posted to Discord: {posting['school']} - {posting['program']}")
                    except discord.HTTPException as e:
                        print(f"Error posting to Discord: {e}")
                        break

        except Exception as e:
            print(f"Error in check_gradcafe_task: {e}")
            import traceback
            traceback.print_exc()

    @check_gradcafe_task.before_loop
    async def before_check_task(self):
        await self.wait_until_ready()

def main():
    if not DISCORD_TOKEN:
        print("Error: DISCORD_TOKEN environment variable not set")
        return

    if DISCORD_CHANNEL_ID == 0:
        print("Error: DISCORD_CHANNEL_ID environment variable not set")
        return

    init_database()
    print("Database initialized")

    intents = discord.Intents.default()
    intents.message_content = True

    client = GradCafeBotWithLLM(intents=intents)
    client.run(DISCORD_TOKEN)

if __name__ == '__main__':
    main()
