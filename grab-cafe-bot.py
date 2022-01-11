
from discord.ext import tasks
import os
import discord
import pandas as pd

class MyClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
        # an attribute we can access from our task
        self.message = ""
    
        # start the task to run in the background
        self.my_background_task.start()
    
    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')
    
    @tasks.loop(seconds=60) # task runs every 60 seconds
    async def my_background_task(self):
        channel = self.get_channel(1234567) # channel ID goes here
        modtime = os.path.getmtime('new_messages.csv')
        
        while True:
          newmodtime = os.path.getmtime("new_messages.csv")
          if(newmodtime > modtime):
            modtime = newmodtime
            d = pd.read_csv("new_messages.csv")
            for i in range(0, d.shape[0]):
              self.message = d['Messages'].loc[i]
              await channel.send(self.counter)
    
    @my_background_task.before_loop
    async def before_my_task(self):
        await self.wait_until_ready() # wait until the bot logs in

client = MyClient()
client.run('token')
