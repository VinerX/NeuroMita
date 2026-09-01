Mita on Python (uses access to neural networks via API) + Melon Mod on Unity, currently not stable.

Mod Server: https://discord.gg/Tu5MPFxM4P

Honestly, GitHub was revealed too early, I'm rushing to provide a temporary demo, but launching it is quite a hassle. If you want stability, wait a couple of months, maybe more.

![logomod3](https://github.com/user-attachments/assets/aea3ec44-c203-4d4a-a405-a09191188464)

Guide on how to set this up, when I more or less finish it)
First, read everything, then proceed, you might change your mind at the sources step(

0) Melon Loader:
Either install it here https://melonwiki.xyz/#/?id=requirements version 0.6.6!!!
Or find it here https://github.com/LavaGang/MelonLoader
Found the MelonLoader.Installer.exe file?
Great, select Misaki there, it will patch it so mods based on Melon can work.

1) My mod comes with Python+prompts+ConversionFolder (place them anywhere together) and also the mod files (MitaAI.dll and assetbudle.test) directly into the mods folder created by Melon (I think I threw them into releases).
https://github.com/VinerX/NeuroMita/releases - here are the releases, i.e., the files needed by a regular player.

   In-game button to write - Tab!

2) The mod in terms of text generation can be launched in two formats.
   
   - Free, using open keys https://openrouter.ai/settings/keys. Most likely, there are hidden limits.
   - Paid, by paying for a key here https://console.proxyapi.ru/billing (Russian option), promo code NEUROMITA for 25% off the first time. Stable, but consider the expenses.
   - If you have direct keys (you're not in Russia), then that's also an option, but currently untested.
   
   Now come the settings that need to be entered in the launched exe application (chat bot)
   Options for model, url, and request button (the last one is purely for the proxy Gemini option):
   
   - ### Free:
      OpenRouter models, get keys here https://openrouter.ai/settings/keys
      - link https://openrouter.ai/api/v1 model google/gemini-2.0-pro-exp-02-05:free (normal mode)
      - link https://openrouter.ai/api/v1 model deepseek/deepseek-chat:free (normal mode)
      - link https://openrouter.ai/api/v1 model google/gemini-exp-1206:free
      - Also try other models https://openrouter.ai/models?max_price=0, write which ones work better
      I'll say right away, they have some limits (per accounts per day), sometimes you can see this in the console, or on the OpenRouter site by trying to write to the model.
   
   
   - ### Paid: 
      Attention, YOU DON'T NEED THE PREM FOR 1500, you can just top up the balance with 200 or more rubles. Again, promo code NEUROMITA for 25% off once. 
      Models from ProxyApi, chosen because you can pay normally in Russia. Find keys and prices here https://console.proxyapi.ru/billing
      - link https://api.proxyapi.ru/openai/v1 model gpt-4o-mini (normal mode)
      - link https://api.proxyapi.ru/google/v1/models/gemini-1.5-flash:generateContent model gemini-1.5-flash (proxy Gemini mode)
   
   In general, you get the idea, you can also look for other options. I'll improve it later, just Gemini has a separate structure + request.

   For those who know, you can try to enter what you need, but it's untested. UPD: for some reason, it's not working yet.

4) Voice generation is done by the Telegram bot Silero @silero_voice_bot, to have Mita's voice you most likely need some kind of prem, check what's available for HD voices and the number of characters (my 66k is more than enough)
There are like 600 characters daily there, test a phrase there manually first, make /mp3 response files for Mita (set up via the menu), and then maybe something will work. I think it's better to buy prem when everything is stable on the mod side.
Especially before buying, check how it works in the game, there was a case where ffmpeg didn't work for a comrade(

6) To use Silero, Telegram API is used, meaning your account (preferably not the main one) turns into a bot, in the sense that it can be controlled from the code. I did this with mine, but assess the risks yourself) Or ask others.
You need api_id and api_hash, here's a guide on how to get them: https://core.telegram.org/api/obtaining_api_id
The source code is there, I mentioned the risks. 
When you enter everything, you'll need to restart and enter the confirmation code in the console, it will come to your Telegram account.
UPD: If there's a cloud password, enter it. It's invisible, but if you enter it correctly and press enter, it will pass.


For those who want to fork and make a pull request - better warn me in advance, I update GitHub very often. 


You read all the way here? Take a cookie from the shelf))

Current developers:
- VinerX
- Nelxi (distrane25) - thanks for help with implementing voice input in Python
- vlad2830 - work on the C# part 
- KASTA - work on the C# part

Thanks for the prompts:
- Feanor and Tkost: Kind Mita
- Josefummi: Short-haired Mita
- gad991: Cap

For the labor-intensive work (in progress) on animations thanks to:
- JPAV

For pull requests thanks to:
- スノー (v1nn1ty)

Acknowledgements - I'll write here so I don't forget anyone:
- Sutherex - he showed me OpenRouter, so double thanks for working with free keys. Helps and has helped organizationally, as well as on the topic of neural networks. And he also made the logo)
- Doctor of Couch Sciences - was there at the dawn, the first tester of just the chat bot, helped with many advices and good ideas. Admins)
- Romancho - helps structure numerous ideas so they don't get forgotten) Also admins and answers questions)
- FlyOfFly - very useful advice and developments on Unity, even helped me attach text input at the beginning)
- LoLY3_0 - Cat on a watermelon)))
- Mr. Sub - his video most likely allowed you to learn about this mod) 
- To all testers of the first days after that video came out (especially smarkloker), it was quite a drag) 

To say thanks to the author, when the mod is brought to stability, it will be possible here https://boosty.to/vinerx