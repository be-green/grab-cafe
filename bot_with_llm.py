import discord
from discord.ext import tasks
import os
import asyncio
import random
from database import init_database, get_unposted_postings, mark_posting_as_posted, format_posting_for_discord, refresh_aggregation_tables
from scraper import fetch_and_store_new_postings
from llm_interface import query_llm

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', '0'))
CHECK_INTERVAL_SECONDS = 60
ENABLE_LLM = 'true'
POST_LOOKBACK_DAYS = 1

# Stock phrases for when the bot is thinking
THINKING_PHRASES = [
    "Consulting the archive...",
    "Searching through the infinite library of admissions data...",
    "Let me peer into the database...",
    "Examining the patterns in the data...",
    "Running through the records...",
    "Querying the admissions archive...",
    "Looking through thousands of applications...",
    "Checking what the data reveals...",
    "Traversing the shelves of the Unending Archive...",
    "One moment while I consult the records...",
]

class GradCafeBotWithLLM(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.llm_loaded = False

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

        if self.user.mentioned_in(message) and not message.mention_everyone:
            if not ENABLE_LLM or not self.llm_loaded:
                await message.channel.send("LLM queries are currently disabled.")
                return

            user_question = message.content.replace(f'<@{self.user.id}>', '').replace(f'<@!{self.user.id}>', '').strip()

            if not user_question:
                await message.channel.send("Hi! Ask me anything about economics graduate admissions data. For example: 'What month do most acceptances come out?' or 'Which schools send the most interviews?'")
                return

            thinking_phrase = random.choice(THINKING_PHRASES)
            await message.channel.send(f"*{thinking_phrase}*")

            try:
                recent_messages = []
                try:
                    async for recent_message in message.channel.history(limit=10, before=message, oldest_first=True):
                        content = recent_message.content.strip()
                        if content:
                            recent_messages.append({
                                "author": recent_message.author.display_name,
                                "content": content
                            })
                except discord.HTTPException as e:
                    print(f"Failed to fetch recent channel context: {e}")

                response_text, plot_filename = await asyncio.to_thread(query_llm, user_question, recent_messages)

                # Add Beatriz's signature
                response_text = f"{response_text}\n\n~Beatriz Viterbo, Head Librarian of the Unending Archive"

                if len(response_text) > 2000:
                    response_text = response_text[:1947] + "...\n\n~Beatriz Viterbo, Head Librarian of the Unending Archive"

                await message.channel.send(response_text)

                if plot_filename and os.path.exists(plot_filename):
                    with open(plot_filename, 'rb') as f:
                        await message.channel.send(file=discord.File(f, plot_filename))
                    os.remove(plot_filename)

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
