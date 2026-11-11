import os, re, base64, hashlib, tempfile
from pathlib import Path
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from openai import OpenAI

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2.5-flare")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
ai = OpenAI(api_key=OPENAI_API_KEY)
accepted_adults = set()

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎨 Создать изображение", callback_data="make")],
        [InlineKeyboardButton(text="ℹ️ Правила и помощь", callback_data="help")]
    ])

def is_blocked(prompt: str) -> bool:
    # Basic guardrail only; provider moderation is also applied.
    p = prompt.lower()
    patterns = [
        r"\b(underage|minor|child|kid|teen| подрост|реб[её]нок|несовершеннолетн)\w*\b",
        r"\b(loli|shota)\b",
        r"\b(non.?consensual|deepfake|without consent|без согласия)\b",
    ]
    return any(re.search(x, p) for x in patterns)

@dp.message(CommandStart())
async def start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мне 18 лет или больше — продолжить", callback_data="adult_yes")]
    ])
    await message.answer(
        "Привет! Я бот для ИИ-генерации изображений и безопасного редактирования. "
        "Нажимая кнопку, ты подтверждаешь, что тебе исполнилось 18 лет.",
        reply_markup=kb
    )

@dp.callback_query(F.data == "adult_yes")
async def adult_yes(call: CallbackQuery):
    accepted_adults.add(call.from_user.id)
    await call.message.edit_text("Возрастное подтверждение принято. Выбери действие:", reply_markup=menu())
    await call.answer()

@dp.callback_query(F.data == "make")
async def make(call: CallbackQuery):
    if call.from_user.id not in accepted_adults:
        await call.answer("Сначала подтверди возраст через /start.", show_alert=True)
        return
    await call.message.answer("Напиши описание изображения. Можно также отправить фото с подписью для безопасного редактирования.")
    await call.answer()

@dp.callback_query(F.data == "help")
async def help_cb(call: CallbackQuery):
    await call.message.answer(
        "Правила: только взрослые персонажи; никаких сексуализированных изображений несовершеннолетних "
        "(в том числе вымышленных), интимных дипфейков или изображений реальных людей без согласия. "
        "Генерация проходит через модерацию провайдера."
    )
    await call.answer()

@dp.message(F.photo)
async def edit_photo(message: Message):
    if message.from_user.id not in accepted_adults:
        await message.answer("Сначала нажми /start и подтверди, что тебе 18+.")
        return
    prompt = message.caption or "Сделай аккуратную, неэксплицитную художественную обработку изображения."
    if is_blocked(prompt):
        await message.answer("Не могу выполнить такой запрос. Попробуй безопасное описание.")
        return
    await message.answer("Обрабатываю изображение…")
    photo = message.photo[-1]
    tg_file = await bot.get_file(photo.file_id)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "input.jpg"
        await bot.download_file(tg_file.file_path, destination=src)
        try:
            result = ai.images.edit(
                model=IMAGE_MODEL,
                image=src.open("rb"),
                prompt=("Edit the supplied image according to this safe request: " + prompt +
                        ". All depicted people must be adults. Do not create nudity, explicit sexual content, "
                        "sexualized minors, non-consensual intimate imagery, or deceptive sexual deepfakes."),
                size="1024x1024",
                quality="medium"
            )
            raw = base64.b64decode(result.data[0].b64_json)
            await message.answer_photo(BufferedInputFile(raw, filename="edited.png"))
        except Exception:
            await message.answer("Не получилось обработать фото. Проверь API-ключ, доступ к модели и попробуй ещё раз.")

@dp.message(F.text)
async def generate(message: Message):
    if message.text.startswith("/"):
        return
    if message.from_user.id not in accepted_adults:
        await message.answer("Сначала нажми /start и подтверди, что тебе 18+.")
        return
    prompt = message.text.strip()
    if is_blocked(prompt):
        await message.answer("Не могу выполнить такой запрос. Попробуй безопасное описание.")
        return
    await message.answer("Создаю изображение…")
    try:
        result = ai.images.generate(
            model=IMAGE_MODEL,
            prompt=("Create a high-quality image based on this request: " + prompt +
                    ". Depict adults only. No nudity, explicit sexual content, sexualized minors, "
                    "non-consensual intimate imagery, or deceptive sexual deepfakes."),
            size="1024x1024",
            quality="medium",
            n=1,
            moderation="auto",
            safety_identifier=hashlib.sha256(str(message.from_user.id).encode()).hexdigest()
        )
        raw = base64.b64decode(result.data[0].b64_json)
        await message.answer_photo(BufferedInputFile(raw, filename="image.png"))
    except Exception:
        await message.answer("Генерация не удалась. Проверь ключ API, биллинг и доступ к модели.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
