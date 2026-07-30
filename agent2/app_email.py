import streamlit as st
import pandas as pd
import os
import smtplib
from email.message import EmailMessage
import imaplib
import email
from email.header import decode_header
import email.utils
from dotenv import load_dotenv
from groq import Groq
from streamlit_autorefresh import st_autorefresh
import json
import datetime
import pytz

# Load environment variables
load_dotenv()

SENT_LOG_FILE = "sent_timestamps.json"

def load_sent_times():
    if os.path.exists(SENT_LOG_FILE):
        try:
            with open(SENT_LOG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_sent_times(data):
    with open(SENT_LOG_FILE, "w") as f:
        json.dump(data, f)


# App configuration
st.set_page_config(page_title="Supplier Matching & Email App", layout="wide")

st.title("Supplier Matching and Email Automation")

# Initialize Session State
if 'process_started' not in st.session_state:
    st.session_state.process_started = False

# Initialize Groq client
groq_api_key = os.getenv("GROQ_API_KEY")
if groq_api_key:
    client = Groq(api_key=groq_api_key)
else:
    st.error("GROQ_API_KEY not found in .env")

# Email credentials from environment
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD") # App password for Gmail

def generate_email(user_name, user_company, user_location, seller_name, seller_category, product_details):
    prompt = f"""
    You are {user_name} from {user_company} located in {user_location}.
    Write a professional and personalized inquiry email to {seller_name}, a supplier of {seller_category}.
    
    We are interested in the following products:
    {product_details}
    
    In the email, please explicitly ask the seller about:
    1. Date of delivery
    2. Available quantity
    3. Advance payment requirements
    4. Terms in case of a return
    
    Make it concise and professional. Do not include placeholders, use the provided information.
    """
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant", 
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error generating email: {e}"

def send_email(to_email, subject, body):
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        return False, "Email credentials not configured in .env."
    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = to_email

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
            
        # Record sent time
        sent_times = load_sent_times()
        sent_times[to_email] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save_sent_times(sent_times)
        
        return True, "Email sent successfully."
    except Exception as e:
        return False, str(e)

def fetch_recent_emails(limit=30):
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        return []
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        mail.select('inbox')
        
        status, messages = mail.search(None, 'ALL')
        if status != 'OK':
            return []
            
        email_ids = messages[0].split()
        latest_email_ids = email_ids[-limit:]
        
        emails_data = []
        for e_id in reversed(latest_email_ids):
            status, msg_data = mail.fetch(e_id, '(RFC822)')
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject, encoding = decode_header(msg['Subject'])[0]
                    if isinstance(subject, bytes):
                        try:
                            subject = subject.decode(encoding if encoding else 'utf-8')
                        except:
                            subject = subject.decode('utf-8', errors='ignore')
                    
                    from_ = msg.get('From')
                    date_ = msg.get('Date')
                    
                    dt = None
                    if date_:
                        try:
                            dt = email.utils.parsedate_to_datetime(date_)
                        except:
                            pass
                    
                    emails_data.append({"From": from_, "Subject": subject, "Date": dt})
        mail.logout()
        return emails_data
    except Exception as e:
        return []



# Create Tabs
tab1, tab2 = st.tabs(["Information & Uploads", "Suppliers & Products"])

with tab1:
    st.header("Step 1: Your Information")
    col1, col2, col3 = st.columns(3)
    with col1:
        user_name = st.text_input("Your Name", key="user_name")
    with col2:
        user_company = st.text_input("Company Name", key="user_company")
    with col3:
        user_location = st.text_input("Your Location", key="user_location")

    st.header("Step 2: Data Uploads")
    col_upload1, col_upload2 = st.columns(2)
    with col_upload1:
        products_file = st.file_uploader("Upload Products CSV", type=["csv"], key="prod_csv")
    with col_upload2:
        sellers_file = st.file_uploader("Upload Sellers CSV", type=["csv"], key="sell_csv")
    
    if products_file and sellers_file:
        if st.button("Start Process"):
            st.session_state.process_started = True
            st.success("Data processed successfully! Please navigate to the 'Suppliers & Products' tab.")

with tab2:
    st.header("Categories, Products & Sellers")
    if not st.session_state.process_started:
        st.info("Please complete the information and upload files in the first tab, then click 'Start Process'.")
    elif products_file and sellers_file:
        # Reset file pointers in case they were read
        products_file.seek(0)
        sellers_file.seek(0)
        
        st.markdown("### Global Auto-Fetch Settings")
        if 'auto_fetch' not in st.session_state:
            st.session_state.auto_fetch = False
        if 'stopped_categories' not in st.session_state:
            st.session_state.stopped_categories = set()
            
        auto_interval_minutes = st.slider("Check Interval (Minutes)", min_value=1, max_value=60, value=5)
        if st.button("Start Auto-Fetch"):
            st.session_state.auto_fetch = True
            st.session_state.stopped_categories = set()
            st.rerun()
            
        if st.session_state.auto_fetch:
            st.success(f"Auto-fetch running (every {auto_interval_minutes} min)")
            st_autorefresh(interval=auto_interval_minutes * 60 * 1000, key="email_autorefresh")
        
        st.markdown("---")
        
        df_products = pd.read_csv(products_file)
        df_sellers = pd.read_csv(sellers_file)
        
        # Clean up column names to be case insensitive and strip spaces
        df_products.columns = [str(c).strip().lower() for c in df_products.columns]
        df_sellers.columns = [str(c).strip().lower() for c in df_sellers.columns]
        
        # Find category columns
        try:
            category_col_prod = [c for c in df_products.columns if 'categor' in c or c == 'cat'][0]
            category_col_sell = [c for c in df_sellers.columns if 'categor' in c or c == 'cat'][0]
        except IndexError:
            st.error("Could not find a 'category' column in one or both of the uploaded CSV files.")
            st.stop()
            
        # Clean category data for better matching
        df_products['clean_cat'] = df_products[category_col_prod].astype(str).str.strip().str.lower()
        df_sellers['clean_cat'] = df_sellers[category_col_sell].astype(str).str.strip().str.lower()
        
        categories = df_products['clean_cat'].dropna().unique()
        
        for cat in categories:
            # Get original category name for display
            display_cat = df_products[df_products['clean_cat'] == cat][category_col_prod].iloc[0]
            
            with st.expander(f"📦 Category: {display_cat}"):
                col_prod, col_sell = st.columns(2)
                
                cat_products = df_products[df_products['clean_cat'] == cat]
                cat_sellers = df_sellers[df_sellers['clean_cat'] == cat]
                
                with col_prod:
                    st.markdown("### Products Needed")
                    st.dataframe(cat_products.drop(columns=['clean_cat']))
                    
                with col_sell:
                    st.markdown("### Available Sellers")
                    if cat_sellers.empty:
                        st.warning(f"No sellers found for category '{display_cat}'.")
                    else:
                        st.dataframe(cat_sellers.drop(columns=['clean_cat']))
                
                if not cat_sellers.empty:
                    col_btn1, col_btn2, col_btn3 = st.columns(3)
                    with col_btn1:
                        if st.button(f"Generate & Send Emails for {display_cat}", key=f"btn_{cat}"):
                            if not st.session_state.user_name or not st.session_state.user_company:
                                st.warning("Please make sure Name and Company are filled out in Tab 1.")
                            else:
                                products_desc = "\n".join([
                                    f"- {row.get('name', 'Product')}: {row.get('description', '')}" 
                                    for _, row in cat_products.iterrows()
                                ])
                                
                                for _, seller in cat_sellers.iterrows():
                                    seller_email = seller.get('email')
                                    seller_name = seller.get('name', 'Supplier')
                                    if pd.isna(seller_email):
                                        continue
                                        
                                    with st.spinner(f"Generating email for {seller_name}..."):
                                        email_body = generate_email(
                                            st.session_state.user_name, 
                                            st.session_state.user_company, 
                                            st.session_state.user_location,
                                            seller_name, 
                                            display_cat, 
                                            products_desc
                                        )
                                    
                                    with st.spinner(f"Sending email to {seller_email}..."):
                                        success, msg = send_email(seller_email, f"Inquiry regarding {display_cat} products", email_body)
                                        
                                    if success:
                                        st.success(f"Email sent to {seller_email}")
                                    else:
                                        st.error(f"Failed to send to {seller_email}: {msg}")
                    
                    with col_btn2:
                        manual_check = st.button(f"Check Replies for {display_cat}", key=f"check_{cat}")
                        
                    with col_btn3:
                        if st.session_state.auto_fetch:
                            if display_cat not in st.session_state.stopped_categories:
                                if st.button(f"Stop Auto-Fetch for {display_cat}", key=f"stop_{cat}"):
                                    st.session_state.stopped_categories.add(display_cat)
                                    st.rerun()
                            else:
                                st.info("Auto-fetch stopped for this category.")
                                
                    should_check = manual_check or (st.session_state.auto_fetch and display_cat not in st.session_state.stopped_categories)
                    
                    if should_check:
                        with st.spinner(f"Checking recent emails for {display_cat}..."):
                            recent_emails = fetch_recent_emails(30) # Fetch more to have a better chance of finding it
                            sent_times = load_sent_times()
                            st.markdown("### Reply Status")
                            for _, seller in cat_sellers.iterrows():
                                seller_email = seller.get('email')
                                seller_name = seller.get('name', 'Supplier')
                                if pd.isna(seller_email):
                                    continue
                                
                                # Get when we sent the email to this seller
                                sent_time_str = sent_times.get(seller_email)
                                sent_time = None
                                if sent_time_str:
                                    try:
                                        sent_time = datetime.datetime.fromisoformat(sent_time_str)
                                    except:
                                        pass
                                        
                                has_replied = False
                                for m in recent_emails:
                                    if str(seller_email).strip().lower() in str(m['From']).lower():
                                        reply_date = m.get('Date')
                                        # If we know when we sent it, and we have a valid reply date, ensure reply came AFTER sent
                                        if sent_time and reply_date:
                                            if reply_date > sent_time:
                                                has_replied = True
                                                break
                                        else:
                                            # Fallback if no sent_time recorded (e.g. before this feature was added)
                                            has_replied = True
                                            break
                                            
                                if has_replied:
                                    st.success(f"✅ {seller_name} ({seller_email}) has replied.")
                                else:
                                    st.warning(f"⏳ Waiting for reply from {seller_name} ({seller_email}).")

