from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime, Text
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from datetime import datetime
import logging
import re
import jdatetime
import pytz

# اضافه کردن کتابخانه‌های مورد نیاز برای Webhook
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

# توکن ربات شما
TOKEN = '7972800273:AAFSPtrNsnzwdvkzzIIosNgOj3fKDf_z7W8'

# شناسه کانال خصوصی شما
CHANNEL_ID = -1002821806086

# اطلاعات Webhook
# آدرس URL سرور شما که تلگرام برای ارسال آپدیت‌ها استفاده می‌کنه.
# باید از HTTPS استفاده بشه.
WEBHOOK_URL = "https://your-domain.com/your_webhook_path"
# پورت مورد نظر شما برای Webhook
PORT = 8443


# --- توابع کمکی ---
def convert_fa_numbers_to_en(text: str) -> str:
    """اعداد فارسی را در یک رشته به اعداد انگلیسی تبدیل می‌کند."""
    persian_digits = "۰۱۲۳۴۴۵۶۷۸۹"
    english_digits = "0123456789"
    translation_table = str.maketrans(persian_digits, english_digits)
    return text.translate(translation_table)

# --- تنظیمات پایگاه داده SQLite ---
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    first_name = Column(String)
    last_name = Column(String)
    phone_number = Column(String)
    
    reports = relationship("Report", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(telegram_id={self.telegram_id}, first_name='{self.first_name}')>"

class Report(Base):
    __tablename__ = 'reports'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    report_text = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow) 

    user = relationship("User", back_populates="reports")

    def __repr__(self):
        return f"<Report(user_id={self.user_id}, timestamp='{self.timestamp}')>"


engine = create_engine('sqlite:///users.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# --- حالت‌های مکالمه (ConversationHandler States) ---
MAIN_MENU, REGISTER_NAME, REGISTER_LAST_NAME, REGISTER_PHONE_NUMBER, SUBMIT_REPORT_TEXT, \
USER_INFO_MENU, EDIT_NAME, EDIT_LAST_NAME, EDIT_PHONE_NUMBER = range(9)

# --- دکمه‌های کیبورد اصلی ---
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("ثبت نام 📝"), KeyboardButton("ثبت گزارش 📊")],
     [KeyboardButton("گزارش‌های اخیر من 📄"), KeyboardButton("نمایش اطلاعات من 👤")]],
    resize_keyboard=True,
    one_time_keyboard=False 
)

# دکمه لغو
CANCEL_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("❌ لغو")]],
    resize_keyboard=True,
    one_time_keyboard=True 
)

# دکمه‌های منوی اطلاعات کاربر
USER_INFO_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("تغییر مشخصات من ✏️")],
     [KeyboardButton("برگشت به منوی اصلی ↩️")]],
    resize_keyboard=True,
    one_time_keyboard=False
)

# --- توابع هندلر (Handler Functions) ---
# (این بخش بدون تغییر است، فقط برای یادآوری اینجا قرار داده شده)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    هندلر دستور /start.
    """
    user_data = update.effective_user
    user_id = user_data.id
    user_first_name = user_data.first_name if user_data.first_name else "دوست عزیز"

    session = Session()
    existing_user = session.query(User).filter_by(telegram_id=user_id).first()
    
    if not existing_user:
        new_user = User(telegram_id=user_id)
        session.add(new_user)
        session.commit()
        print(f"User {user_id} added to DB.")
        welcome_message = f"سلام {user_first_name} عزیز! 👋 به ربات گزارش درسی خوش اومدی." \
                          "\nبرای استفاده از ربات، یکی از گزینه‌های زیر رو انتخاب کن:"
        await update.message.reply_text(welcome_message, reply_markup=MAIN_KEYBOARD)
    else:
        print(f"User {user_id} already exists in DB.")
        await update.message.reply_text("خوش برگشتی! 👋 از منوی زیر یکی از گزینه‌ها رو انتخاب کن:", reply_markup=MAIN_KEYBOARD)
    session.close()
    
    return MAIN_MENU

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    نمایش منوی اصلی (ارسال پیام جدید).
    """
    await update.effective_chat.send_message("از منوی زیر یکی از گزینه‌ها رو انتخاب کن:", reply_markup=MAIN_KEYBOARD)
    return MAIN_MENU

async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    شروع فرآیند ثبت نام.
    """
    session = Session()
    user_id = update.effective_user.id
    registered_user = session.query(User).filter_by(telegram_id=user_id).first()
    session.close()

    if registered_user and all([registered_user.first_name, registered_user.last_name, registered_user.phone_number]):
        await update.effective_chat.send_message("شما قبلاً ثبت نام کرده‌اید! ✅ برای تغییر مشخصات از 'نمایش اطلاعات من' و سپس 'تغییر مشخصات من' استفاده کنید.", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU
    
    await update.effective_chat.send_message(
        "لطفاً نام خودت رو وارد کن: 👇",
        reply_markup=CANCEL_KEYBOARD
    )

    return REGISTER_NAME

async def get_register_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    نام کاربر را دریافت کرده و آن را در context.user_data ذخیره می‌کند.
    سپس از کاربر می‌خواهد نام خانوادگی خود را وارد کند.
    """
    user_name = update.message.text.strip()
    if not re.fullmatch(r"^[ا-یa-zA-Z\s]{2,}$", user_name):
        await update.effective_chat.send_message("لطفاً یک نام معتبر (فقط حروف، حداقل ۲ کاراکتر) وارد کن: 📛", reply_markup=CANCEL_KEYBOARD)
        return REGISTER_NAME
    
    context.user_data['first_name'] = user_name
    
    await update.effective_chat.send_message(
        "حالا لطفاً نام خانوادگی خودت رو وارد کن: ✍️",
        reply_markup=CANCEL_KEYBOARD
    )
    return REGISTER_LAST_NAME

async def get_register_last_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    نام خانوادگی کاربر را دریافت کرده و آن را در context.user_data ذخیره می‌کند.
    سپس از کاربر می‌خواهد شماره تماس خود را وارد کند.
    """
    user_last_name = update.message.text.strip()
    if not re.fullmatch(r"^[ا-یa-zA-Z\s]{2,}$", user_last_name):
        await update.effective_chat.send_message("لطفاً یک نام خانوادگی معتبر (فقط حروف، حداقل ۲ کاراکتر) وارد کن: 📛", reply_markup=CANCEL_KEYBOARD)
        return REGISTER_LAST_NAME
        
    context.user_data['last_name'] = user_last_name

    await update.effective_chat.send_message(
        "لطفاً شماره تماس خودت رو وارد کن (مثال: 09123456789): 📱",
        reply_markup=CANCEL_KEYBOARD
    )
    return REGISTER_PHONE_NUMBER

async def get_register_phone_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    شماره تماس کاربر را دریافت کرده و آن را در context.user_data ذخیره می‌کند.
    اطلاعات ثبت نام را در پایگاه داده ذخیره و به منوی اصلی باز می‌گردد.
    """
    phone_number = convert_fa_numbers_to_en(update.message.text.strip()) 
    
    if not re.fullmatch(r"^09\d{9}$", phone_number):
        await update.effective_chat.send_message("لطفاً یک شماره تماس ۱۱ رقمی معتبر که با '09' شروع می‌شود، وارد کن: 📱", reply_markup=CANCEL_KEYBOARD)
        return REGISTER_PHONE_NUMBER

    context.user_data['phone_number'] = phone_number

    session = Session()
    user_id = update.effective_user.id
    user_to_update = session.query(User).filter_by(telegram_id=user_id).first()

    if user_to_update:
        user_to_update.first_name = context.user_data.get('first_name')
        user_to_update.last_name = context.user_data.get('last_name')
        user_to_update.phone_number = context.user_data.get('phone_number')
        session.commit()
        await update.effective_chat.send_message("✅ اطلاعات شما با موفقیت ثبت شد! ممنون.")
        print(f"User {user_id} registration data saved/updated in DB.")
    else:
        await update.effective_chat.send_message("متاسفانه مشکلی در ذخیره اطلاعات پیش اومد. لطفاً دوباره /start رو بزنید.")
        print(f"Error: User {user_id} not found in DB for registration update.")
    session.close()

    context.user_data.clear()
    return await show_main_menu(update, context)

async def report_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    شروع فرآیند ثبت گزارش.
    """
    session = Session()
    user_id = update.effective_user.id
    registered_user = session.query(User).filter_by(telegram_id=user_id).first()
    session.close()

    if not registered_user or not all([registered_user.first_name, registered_user.last_name, registered_user.phone_number]):
        await update.effective_chat.send_message("⚠️ ابتدا باید مشخصات خودت رو ثبت کنی! لطفاً از دکمه 'ثبت نام' استفاده کن.", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU
    else:
        context.user_data['current_user_db_id'] = registered_user.id
        context.user_data['first_name'] = registered_user.first_name
        context.user_data['last_name'] = registered_user.last_name
        context.user_data['phone_number'] = registered_user.phone_number
        
        await update.effective_chat.send_message(
            "لطفاً متن گزارش کار خودت رو وارد کن: 📝",
            reply_markup=CANCEL_KEYBOARD
        )
        return SUBMIT_REPORT_TEXT

async def get_report_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    متن گزارش کار را دریافت کرده و تمام اطلاعات را در پایگاه داده ذخیره می‌کند.
    """
    report_text = update.message.text.strip()
    if len(report_text) < 5:
        await update.effective_chat.send_message("متن گزارش شما خیلی کوتاه است. لطفاً حداقل ۵ کاراکتر وارد کنید: 📝", reply_markup=CANCEL_KEYBOARD)
        return SUBMIT_REPORT_TEXT

    session = Session()
    user_db_id = context.user_data.get('current_user_db_id')
    
    if user_db_id:
        new_report = Report(user_id=user_db_id, report_text=report_text)
        session.add(new_report)
        session.commit()
        await update.effective_chat.send_message("✅ گزارش شما با موفقیت ثبت شد! ممنون از شما.")
        print(f"New report for user {user_db_id} saved in DB. Report ID: {new_report.id}")

        report_message = (
            f"📊 **گزارش کار جدید**\n"
            f"🧑‍🎓 **نام:** {context.user_data.get('first_name')}\n"
            f"👨‍🎓 **نام خانوادگی:** {context.user_data.get('last_name')}\n"
            f"📞 **شماره تماس:** `{context.user_data.get('phone_number')}`\n"
            f"```\n" 
            f"📝 متن گزارش:\n{report_text}\n"
            f"```" 
        )
        try:
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=report_message,
                parse_mode='Markdown'
            )
            print(f"Report sent to channel {CHANNEL_ID}.")
        except Exception as e:
            print(f"Error sending report to channel: {e}")
            await update.effective_chat.send_message("❗️مشکلی در ارسال گزارش به کانال پیش اومد. لطفاً به ادمین اطلاع بدید.")

    else:
        await update.effective_chat.send_message("متاسفانه مشکلی در ثبت گزارش پیش اومد. لطفاً دوباره /start رو بزنید.")
        print(f"Error: User DB ID not found for report submission.")
    session.close()

    context.user_data.clear() 
    return await show_main_menu(update, context) 

async def show_my_reports(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    نمایش گزارش‌های اخیر کاربر.
    """
    session = Session()
    user_telegram_id = update.effective_user.id
    user = session.query(User).filter_by(telegram_id=user_telegram_id).first()

    if not user or not user.reports:
        await update.effective_chat.send_message("شما هنوز گزارشی ثبت نکرده‌اید! 🙁", reply_markup=MAIN_KEYBOARD)
        session.close()
        return MAIN_MENU

    reports_text = []
    recent_reports = session.query(Report).filter_by(user_id=user.id).order_by(Report.timestamp.desc()).limit(5).all()

    if recent_reports:
        reports_text.append("📄 **آخرین گزارش‌های شما:**\n")
        tehran_tz = pytz.timezone('Asia/Tehran')

        for i, report in enumerate(recent_reports):
            utc_dt = report.timestamp.replace(tzinfo=pytz.utc)
            tehran_dt = utc_dt.astimezone(tehran_tz)
            j_date = jdatetime.datetime.fromgregorian(datetime=tehran_dt)
            persian_timestamp = j_date.strftime("%Y/%m/%d %H:%M:%S")
            
            reports_text.append(f"---")
            reports_text.append(f"**{i+1}. تاریخ و زمان:** {persian_timestamp}")
            reports_text.append(f"```\n{report.report_text}\n```")
        
        await update.effective_chat.send_message(
            "\n".join(reports_text),
            parse_mode='Markdown',
            reply_markup=MAIN_KEYBOARD
        )
    else:
        await update.effective_chat.send_message("شما هنوز گزارشی ثبت نکرده‌اید! 🙁", reply_markup=MAIN_KEYBOARD)
    
    session.close()
    return MAIN_MENU


async def show_my_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    نمایش اطلاعات ثبت شده کاربر و دکمه تغییر مشخصات.
    """
    session = Session()
    user_telegram_id = update.effective_user.id
    user = session.query(User).filter_by(telegram_id=user_telegram_id).first()
    session.close()

    if not user or not all([user.first_name, user.last_name, user.phone_number]):
        await update.effective_chat.send_message("شما هنوز مشخصاتی ثبت نکرده‌اید! 😔 لطفاً ابتدا 'ثبت نام' کنید.", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU
    
    info_message = (
        f"👤 **اطلاعات شما:**\n"
        f"**نام:** {user.first_name}\n"
        f"**نام خانوادگی:** {user.last_name}\n"
        f"**شماره تماس:** `{user.phone_number}`\n\n"
        f"برای تغییر مشخصات، از دکمه زیر استفاده کنید:"
    )
    await update.effective_chat.send_message(info_message, parse_mode='Markdown', reply_markup=USER_INFO_KEYBOARD)
    return USER_INFO_MENU

async def edit_my_info_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    شروع فرآیند تغییر مشخصات کاربر.
    """
    await update.effective_chat.send_message("لطفاً نام جدید خودت رو وارد کن: 👇", reply_markup=CANCEL_KEYBOARD)
    return EDIT_NAME

async def get_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_name = update.message.text.strip()
    if not re.fullmatch(r"^[ا-یa-zA-Z\s]{2,}$", user_name):
        await update.effective_chat.send_message("لطفاً یک نام معتبر (فقط حروف، حداقل ۲ کاراکتر) وارد کن: 📛", reply_markup=CANCEL_KEYBOARD)
        return EDIT_NAME
        
    context.user_data['first_name'] = user_name
    await update.effective_chat.send_message("حالا لطفاً نام خانوادگی جدید خودت رو وارد کن: ✍️", reply_markup=CANCEL_KEYBOARD)
    return EDIT_LAST_NAME

async def get_edit_last_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_last_name = update.message.text.strip()
    if not re.fullmatch(r"^[ا-یa-zA-Z\s]{2,}$", user_last_name):
        await update.effective_chat.send_message("لطفاً یک نام خانوادگی معتبر (فقط حروف، حداقل ۲ کاراکتر) وارد کن: 📛", reply_markup=CANCEL_KEYBOARD)
        return EDIT_LAST_NAME
        
    context.user_data['last_name'] = user_last_name
    await update.effective_chat.send_message("لطفاً شماره تماس جدید خودت رو وارد کن (مثال: 09123456789): 📱", reply_markup=CANCEL_KEYBOARD)
    return EDIT_PHONE_NUMBER

async def get_edit_phone_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone_number = convert_fa_numbers_to_en(update.message.text.strip())
    
    if not re.fullmatch(r"^09\d{9}$", phone_number):
        await update.effective_chat.send_message("لطفاً یک شماره تماس ۱۱ رقمی معتبر که با '09' شروع می‌شود، وارد کن: 📱", reply_markup=CANCEL_KEYBOARD)
        return EDIT_PHONE_NUMBER

    context.user_data['phone_number'] = phone_number

    session = Session()
    user_id = update.effective_user.id
    user_to_update = session.query(User).filter_by(telegram_id=user_id).first()

    if user_to_update:
        user_to_update.first_name = context.user_data.get('first_name')
        user_to_update.last_name = context.user_data.get('last_name')
        user_to_update.phone_number = context.user_data.get('phone_number')
        session.commit()
        await update.effective_chat.send_message("✅ مشخصات شما با موفقیت به‌روز شد! ممنون.")
        print(f"User {user_id} info updated in DB.")
    else:
        await update.effective_chat.send_message("متاسفانه مشکلی در به‌روزرسانی اطلاعات پیش اومد. لطفاً دوباره تلاش کنید.")
        print(f"Error: User {user_id} not found in DB for info update.")
    session.close()

    context.user_data.clear()
    return await show_my_info(update, context) 


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    هندلر دکمه لغو یا دستور /cancel.
    """
    await update.effective_chat.send_message("عملیات لغو شد. ❌")
    
    context.user_data.clear()
    return await show_main_menu(update, context)

# --- تابع اصلی (Main Function) ---
def main() -> None:
    """ربات را راه‌اندازی می‌کند."""
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                MessageHandler(filters.Regex("^ثبت نام 📝$"), register_start),
                MessageHandler(filters.Regex("^ثبت گزارش 📊$"), report_start),
                MessageHandler(filters.Regex("^گزارش‌های اخیر من 📄$"), show_my_reports),
                MessageHandler(filters.Regex("^نمایش اطلاعات من 👤$"), show_my_info),
            ],
            REGISTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ لغو$"), get_register_name)],
            REGISTER_LAST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ لغو$"), get_register_last_name)],
            REGISTER_PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ لغو$"), get_register_phone_number)],
            SUBMIT_REPORT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ لغو$"), get_report_text)],
            USER_INFO_MENU: [
                MessageHandler(filters.Regex("^تغییر مشخصات من ✏️$"), edit_my_info_start),
                MessageHandler(filters.Regex("^برگشت به منوی اصلی ↩️$"), show_main_menu),
            ],
            EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ لغو$"), get_edit_name)],
            EDIT_LAST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ لغو$"), get_edit_last_name)],
            EDIT_PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ لغو$"), get_edit_phone_number)],
        },
        fallbacks=[
            MessageHandler(filters.Regex("^❌ لغو$"), cancel),
            CommandHandler("cancel", cancel)
        ],
    )

    application.add_handler(conv_handler)
    
    # --- بخش جدید Webhook ---
    async def run() -> None:
        """اجرای ربات با استفاده از Webhook."""
        # اگر در یک محیط مثل Heroku یا سرویس‌های ابری هستید، پورت از متغیر محیطی گرفته می‌شود.
        # در غیر این صورت، از پورت پیش‌فرض 8443 استفاده می‌کنیم.
        port = int(os.environ.get("PORT", PORT))

        # ایجاد یک سرور موقت برای شنیدن درخواست‌های تلگرام
        # این بخش باید در سرور واقعی با یک سرور HTTP قدرتمندتر (مثل gunicorn) جایگزین شود
        # همچنین برای استفاده از HTTPS به گواهینامه SSL نیاز دارید.
        await application.run_webhook(listen="0.0.0.0", port=port, url_path=WEBHOOK_URL, webhook_url=f"https://{os.environ.get('WEBHOOK_HOST', 'your-domain.com')}/", cert=None)

    application.run(run())

if __name__ == "__main__":
    main()