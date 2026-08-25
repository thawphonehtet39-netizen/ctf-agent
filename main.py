import os
import json
import subprocess
import asyncio
import logging
import hashlib
from datetime import datetime

from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# === Configuration ===
TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
WEBHOOK_URL = f"https://ctf-agent.onrender.com/webhook"

# Flask app
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# === Groq LLM Client ===
from openai import OpenAI
llm_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

# === Conversation Memory ===
conversations = {}

def get_conversation(chat_id):
    if chat_id not in conversations:
        conversations[chat_id] = [
            {"role": "system", "content": """You are CTF Agent — an expert CTF solver and cybersecurity AI assistant.
Solve CTF challenges, write exploit code, search the web, explain techniques, and chat naturally.
You have full Linux access via /exec, Python with pwntools, and internet search via /search.
When solving CTFs, analyze step by step and write working exploits."""}
        ]
    return conversations[chat_id]

# === Telegram Bot ===
bot_app = Application.builder().token(TOKEN).build()

@app.route('/')
def home():
    return "🤖 CTF Agent 24/7 Ready"

@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot_app.bot)
    asyncio.run(handle_update(update))
    return 'OK', 200

@app.route('/health')
def health():
    return 'alive', 200

async def handle_update(update):
    if not update.message or not update.message.text:
        return
    chat_id = update.message.chat_id
    text = update.message.text.strip()
    await bot_app.bot.send_chat_action(chat_id=chat_id, action="typing")
    if text.startswith('/'):
        await handle_command(update, text)
    else:
        await handle_chat(update, text)

async def handle_command(update, text):
    chat_id = update.message.chat_id
    if text == '/start':
        await update.message.reply_text(
            "🤖 **CTF Agent Ready**\n\n"
            "ငါက CTF challenges တွေဖြေပေးတယ်၊ စကားပြောပေးတယ်၊ internet ကရှာပေးတယ်။\n\n"
            "**Commands:**\n"
            "• စာရိုက်ပြီးပြော — ငါနဲ့စကားပြောမယ်\n"
            "• `/exec <cmd>` — Shell command run\n"
            "• `/solve <url>` — CTF download & analyze\n"
            "• `/search <query>` — Internet ကရှာပေး\n"
            "• `/clear` — Chat history ရှင်း\n"
            "• `/status` — System info"
        )
    elif text.startswith('/exec '):
        cmd = text[6:]
        await update.message.reply_text(f"⚙️ `{cmd}`")
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
            output = (result.stdout or result.stderr)[:4000]
            await update.message.reply_text(f"```\n{output}\n```")
        except subprocess.TimeoutExpired:
            await update.message.reply_text("⏰ Timed out (120s)")
        except Exception as e:
            await update.message.reply_text(f"❌ {str(e)}")
    elif text.startswith('/search '):
        query = text[8:]
        await update.message.reply_text(f"🔍 Searching: {query}")
        result = await web_search(query)
        summary = await ask_llm([{"role": "user", "content": f"Search results for '{query}':\n{result}\n\nSummarize in Burmese:"}])
        await update.message.reply_text(summary[:4000])
    elif text.startswith('/solve '):
        target = text[7:]
        await update.message.reply_text(f"📥 Downloading: {target}\n⏳ Analyzing...")
        await solve_ctf_challenge(chat_id, target)
    elif text == '/clear':
        conversations[chat_id] = [conversations[chat_id][0]]
        await update.message.reply_text("🧹 Memory cleared!")
    elif text == '/status':
        uname = subprocess.run(['uname', '-a'], capture_output=True, text=True).stdout
        df = subprocess.run(['df', '-h', '/'], capture_output=True, text=True).stdout
        await update.message.reply_text(f"🖥 **Status**\n\n```\n{uname}\n{df}\n```")

async def handle_chat(update, text):
    chat_id = update.message.chat_id
    history = get_conversation(chat_id)
    history.append({"role": "user", "content": text})
    if len(history) > 20:
        history = [history[0]] + history[-19:]
        conversations[chat_id] = history
    try:
        response = await ask_llm(history)
        history.append({"role": "assistant", "content": response})
        await update.message.reply_text(response[:4000])
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def ask_llm(messages):
    loop = asyncio.get_event_loop()
    def sync_call():
        completion = llm_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.7,
            max_tokens=4096
        )
        return completion.choices[0].message.content
    return await loop.run_in_executor(None, sync_call)

async def web_search(query):
    try:
        from duckduckgo_search import DDGS
        loop = asyncio.get_event_loop()
        def search():
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
                formatted = ""
                for r in results:
                    formatted += f"**{r['title']}**\n{r['href']}\n{r['body']}\n\n"
                return formatted or "No results."
        return await loop.run_in_executor(None, search)
    except Exception as e:
        return f"Search error: {str(e)}"

async def solve_ctf_challenge(chat_id, target):
    await bot_app.bot.send_message(chat_id, "📥 Step 1: Downloading...")
    filename = f"/tmp/challenge_{hashlib.md5(target.encode()).hexdigest()[:8]}"
    try:
        subprocess.run(f"wget -q -O {filename} '{target}'", shell=True, timeout=30)
        file_type = subprocess.run(['file', filename], capture_output=True, text=True).stdout
        await bot_app.bot.send_message(chat_id, f"📄 **File:**\n```\n{file_type}\n```")
        strings_out = subprocess.run(['strings', filename], capture_output=True, text=True, timeout=10).stdout[-2000:]
        await bot_app.bot.send_message(chat_id, "🧠 Step 2: AI analyzing...")
        conv = get_conversation(chat_id)
        conv.append({"role": "user", "content": f"CTF Challenge:\nURL: {target}\nType: {file_type}\nStrings: {strings_out[:1000]}\n\nAnalyze and write exploit code:"})
        response = await ask_llm(conv)
        conv.append({"role": "assistant", "content": response})
        await bot_app.bot.send_message(chat_id, f"🔍 **Analysis:**\n\n{response[:4000]}")
    except Exception as e:
        await bot_app.bot.send_message(chat_id, f"❌ Error: {str(e)}")

def setup_webhook():
    from telegram import Bot
    bot = Bot(TOKEN)
    bot.set_webhook(url=WEBHOOK_URL)
    logging.info(f"✅ Webhook set to {WEBHOOK_URL}")

if __name__ == '__main__':
    setup_webhook()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
