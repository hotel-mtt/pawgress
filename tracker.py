"""
tracker.py — Pawgress QC Dashboard
Streamlit · Google Sheets backend
"""
import streamlit as st
import pandas as pd
import gspread
import pytz
import time
import plotly.graph_objects as go
import streamlit.components.v1 as components
from google.oauth2.service_account import Credentials
from datetime import datetime, date, timedelta

# ── App Configuration ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Pawgress · QC Dashboard",
    page_icon="🐾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ─────────────────────────────────────────────────────────────────
SHEET_ID             = "14J8ptb6YIkBAJXLpNSpFPC_EtT3H24Mcyo2UPHmSMcw"
SLA_TARGET           = 60
DONE_BONUS           = 5
QC_BONUS             = 10
QC_FOUND_BONUS       = 15
IDLE_TIMEOUT_MINUTES = 15
IDLE_TIMEOUT_MS      = IDLE_TIMEOUT_MINUTES * 60 * 1000

TASK_TYPES = {
    "Booking Hotel":        ("🏨", "Reservasi",  10, "Booking baru hotel reguler"),
    "Booking Urgent":       ("⚡", "Reservasi",  25, "Booking prioritas / deadline mepet"),
    "Revisi Booking":       ("✏️", "Reservasi",  10, "Perubahan, relokasi atau amandemen booking"),
    "Pengajuan Pembayaran": ("💳", "Payment",    15, "Submit pembayaran ke supplier"),
    "Follow Up Payment":    ("💳", "Payment",     5, "Follow up status pembayaran"),
    "Inject DTM":           ("💳", "Payment",     5, "Inject pembayaran DTM"),
    "Rekap Tagihan":        ("📊", "Payment",    20, "Rekap & laporan tagihan"),
    "Refund":               ("↩️", "Payment",    10, "Proses pengembalian dana"),
    "Void":                 ("🚫", "Reservasi",   5, "Pembatalan / void transaksi"),
    "Reconfirmed":          ("🆗", "Reservasi",  15, "Reconfirmed / HCN Number"),
}
PENALTY_TYPES = {
    "Kesalahan Input Data":  ("❌", "Penalti", -10, "Data yang diinput salah"),
    "Revisi Berulang":       ("🔄", "Penalti",  -5, "Revisi yang seharusnya bisa dihindari"),
    "Keterlambatan Input":   ("⏰", "Penalti",  -5, "Input data terlambat"),
    "Void Akibat Kelalaian": ("🚫", "Penalti", -25, "Void karena kesalahan sendiri"),
    "Komplain Tamu":         ("😠", "Penalti", -35, "Tamu komplain akibat kelalaian"),
    "Data Tidak Lengkap":    ("📋", "Penalti",  -5, "Booking tanpa info lengkap"),
}
ALL_OPTIONS = list(TASK_TYPES.keys()) + list(PENALTY_TYPES.keys())

ROLES = {
    "Manager": {"color": "var(--pur)", "av_class": "manager", "emoji": "👑", "desc": "Full Access"},
    "Finance": {"color": "var(--blu)", "av_class": "finance", "emoji": "💳", "desc": "QC & Payment"},
    "Booker":  {"color": "var(--g)",   "av_class": "booker",  "emoji": "🏨", "desc": "Reservasi"},
}
ALL_STAFF = {
    "Manager": ["Manager"],
    "Finance": sorted(["Fandi", "Yati", "Riega"]),
    "Booker":  sorted(["Vial", "Vero", "Geraldi", "Farras", "Baldy", "Meiji", "Rida", "Ade", "Selvy", "Firda"]),
}
ALL_STAFF_FLAT = ["Manager"] + ALL_STAFF["Finance"] + ALL_STAFF["Booker"]
STAFF_ROLE_MAP = {s: r for r, members in ALL_STAFF.items() for s in members}
PASSWORDS = {
    "Manager": "789789", "Vero": "vero123", "Yati": "yati123",
    "Ade": "ade123", "Selvy": "selvy123", "Firda": "firda123",
    "Vial": "vial123", "Fandi": "fandi123", "Geraldi": "geraldi123",
    "Riega": "riega123", "Farras": "farras123", "Baldy": "baldy123",
    "Meiji": "meiji123", "Rida": "rida123",
}
STATUS_LIST = ["Done", "In Progress", "Pending", "Waiting Confirmation", "On Hold", "Cancelled"]
QC_STATUS   = ["Pending QC", "OK", "Ada Isu"]

LEVELS = [
    (20,    "🐾 Kitten"),
    (100,   "🐱 Kucing Kampung"),
    (300,   "🐈 Oyen"),
    (600,   "🐈‍⬛ Kucing Garong"),
    (1000,  "🐆 Kucing Elite"),
    (1800,  "🐅 Kucing Sultan"),
    (3000,  "👑 King of Paw"),
]
LEVEL_CAT_MAP = {
    "🐾 Kitten":         ("kitten",  "#9ca3af"),
    "🐱 Kucing Kampung": ("kampung", "#f59e0b"),
    "🐈 Oyen":           ("oyen",    "#f97316"),
    "🐈‍⬛ Kucing Garong": ("garong",  "#64748b"),
    "🐆 Kucing Elite":   ("elite",   "#7c3aed"),
    "🐅 Kucing Sultan":  ("sultan",  "#dc2626"),
    "👑 King of Paw":    ("king",    "#d97706"),
}

HEADERS = [
    "Date","Staff","Role","Kategori","Task Type","Booking ID",
    "Hotel","Notes","Status","Poin","Timestamp","Timestamp Edit",
    "SLA Minutes","QC Finance","QC Booker","QC Notes","Error Flag",
]
QC_HEADERS       = ["Date","QC By","QC Role","Target Staff","Booking ID","Task Type","QC Status","QC Notes","XP Awarded","Timestamp"]
SESSION_HEADERS  = ["Date","Staff","Role","Login Time","Logout Time","Duration Minutes","Status"]
QC_SCORE_HEADERS = ["Staff","Total QC","Correct","Miss","Accuracy","Last Updated"]

TZ_JKT     = pytz.timezone("Asia/Jakarta")
ROLE_COLOR = {"Manager": "var(--pur)", "Finance": "var(--blu)", "Booker": "var(--g)"}
ROLE_CLASS = {"Manager": "manager", "Finance": "finance", "Booker": "booker"}
CHART_GREENS = ["#88bc77","#cfe5a4","#8f7872","#f8b2b0","#2a9640","#96d8a0","#d4b8b4","#b0c890","#1e7a32","#e8d4c4"]

# ── CSS ───────────────────────────────────────────────────────────────────────
GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap');
:root {
    --g:#88bc77; --g2:#2a9640; --gdk:#1e7a32; --g3:#248a3a;
    --glt:#e8f8eb; --gmd:#96d8a0; --gxlt:#f2fdf4;
    --pos:#cfe5a4; --posdk:#8aac50; --poslt:#f4fae8; --posmd:#c0d98e;
    --neg:#d4736f; --neglt:#fef0ef; --negmd:#f8b2b0;
    --urg:#8f7872; --urglt:#f8f2f1; --urgmd:#d4b8b4;
    --blu:#5c8fa1; --bllt:#eef4f7; --blmd:#a8cad6;
    --pur:#8f7872; --purlt:#f8f2f1; --purmd:#d4b8b4;
    --bg:#faf8f6; --wh:#ffffff; --bd:#e8e2de; --bd2:#f0ece8;
    --tx:#2c2825; --mu:#7a6e6a; --fa:#b0a49e;
    --r:14px; --rs:10px; --rl:18px; --rpill:999px;
    --sh:0 1px 4px rgba(44,40,37,0.07),0 2px 12px rgba(44,40,37,0.05);
    --shm:0 6px 22px rgba(44,40,37,0.12);
    --shl:0 14px 44px rgba(44,40,37,0.14);
    --shg:0 4px 18px rgba(60,174,80,0.22);
}
html,body,[class*="css"]{font-family:'Nunito',sans-serif!important;background:var(--bg)!important;color:var(--tx)!important;}
.stApp{background:var(--bg)!important;}
#MainMenu,footer,header{visibility:hidden;}
.block-container{padding-top:1.2rem!important;padding-bottom:2rem!important;max-width:1300px!important;}
.stApp::before{content:'🐾';position:fixed;font-size:180px;opacity:0.025;bottom:-20px;right:-20px;pointer-events:none;z-index:0;transform:rotate(-15deg);}
section[data-testid="stSidebar"]{background:var(--wh)!important;border-right:1px solid var(--bd)!important;box-shadow:2px 0 16px rgba(44,40,37,0.06)!important;}
section[data-testid="stSidebar"]>div{padding-top:0!important;}
section[data-testid="stSidebar"] *{color:var(--tx)!important;}
section[data-testid="stSidebar"] hr{border-color:var(--bd)!important;}
section[data-testid="stSidebar"] .stSelectbox>div>div{background:var(--bg)!important;border:1px solid var(--bd)!important;}
.sb-head{background:linear-gradient(135deg,var(--gdk),var(--g));padding:22px 18px 20px;position:relative;overflow:hidden;}
.sb-head::before{content:'🐾';position:absolute;font-size:72px;opacity:0.12;top:-10px;right:-10px;transform:rotate(20deg);pointer-events:none;}
.sb-head::after{content:'🐱';position:absolute;font-size:28px;opacity:0.18;bottom:4px;left:14px;pointer-events:none;}
.sb-head-inner{display:flex;align-items:center;gap:12px;position:relative;z-index:1;}
.sb-ico{width:38px;height:38px;background:rgba(255,255,255,0.22);border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;backdrop-filter:blur(4px);box-shadow:0 2px 8px rgba(0,0,0,0.12);}
.sb-title{font-size:15px;font-weight:900;color:#fff!important;letter-spacing:-.3px;}
.sb-sub{font-size:9px;color:rgba(255,255,255,0.55)!important;text-transform:uppercase;letter-spacing:1.4px;margin-top:2px;}
.sb-lbl{font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:1.8px;color:var(--fa)!important;padding:14px 16px 5px;display:flex;align-items:center;gap:6px;}
.sb-lbl::before{content:'🐾';font-size:10px;opacity:0.5;}
.role-chip{display:flex;align-items:center;gap:8px;margin:10px 14px 4px;padding:9px 13px;border-radius:12px;font-size:11px;font-weight:700;}
.rc-manager{background:var(--urglt);color:var(--urg);border:1px solid var(--urgmd);}
.rc-finance{background:var(--bllt);color:var(--blu);border:1px solid var(--blmd);}
.rc-booker{background:var(--glt);color:var(--gdk);border:1px solid var(--gmd);}
.rc-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;}
.rc-manager .rc-dot{background:var(--urg);}
.rc-finance .rc-dot{background:var(--blu);}
.rc-booker .rc-dot{background:var(--g);}
.sb-stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:0 12px 10px;}
.sb-stat{background:var(--bg);border:1px solid var(--bd);border-radius:11px;padding:9px 11px;}
.sb-stat-v{font-size:19px;font-weight:800;color:var(--tx)!important;font-family:'JetBrains Mono',monospace;line-height:1;}
.sb-stat-v.g{color:var(--gdk)!important;}.sb-stat-v.r{color:var(--neg)!important;}.sb-stat-v.y{color:var(--urg)!important;}.sb-stat-v.b{color:var(--blu)!important;}
.sb-stat-l{font-size:8px;color:var(--mu)!important;text-transform:uppercase;letter-spacing:.7px;margin-top:3px;}
.sb-xp{margin:0 12px 8px;}
.sb-xp-row{display:flex;justify-content:space-between;font-size:10px;margin-bottom:5px;}
.sb-xp-lbl{color:var(--mu)!important;font-weight:600;}
.sb-xp-val{color:var(--g)!important;font-weight:700;font-family:'JetBrains Mono',monospace;}
.sb-xp-track{background:var(--bd);border-radius:99px;height:6px;overflow:hidden;}
.sb-xp-fill{height:100%;background:linear-gradient(90deg,var(--g),var(--pos));border-radius:99px;}
.staff-bar{background:var(--wh);border:1px solid var(--bd);border-radius:var(--r);padding:14px 20px;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between;box-shadow:var(--sh);position:relative;overflow:hidden;}
.staff-bar::after{content:'🐾';position:absolute;right:12px;top:50%;transform:translateY(-50%) rotate(30deg);font-size:48px;opacity:0.04;pointer-events:none;}
.sbar-l{display:flex;align-items:center;gap:13px;}
.sbar-av{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:800;color:#fff;font-family:'JetBrains Mono',monospace;flex-shrink:0;}
.sbar-av.manager{background:linear-gradient(135deg,var(--urg),#b09090);}
.sbar-av.finance{background:linear-gradient(135deg,var(--blu),#7ab0c0);}
.sbar-av.booker{background:linear-gradient(135deg,var(--g),var(--g2));}
.sbar-name{font-size:16px;font-weight:800;color:var(--tx);letter-spacing:-.3px;}
.sbar-sub{font-size:11px;color:var(--mu);margin-top:2px;}
.sbar-r{display:flex;align-items:center;gap:20px;}
.sbar-stat{text-align:right;}
.sbar-stat-v{font-size:19px;font-weight:800;font-family:'JetBrains Mono',monospace;color:var(--tx);line-height:1;}
.sbar-stat-v.g{color:var(--gdk);}.sbar-stat-v.r{color:var(--neg);}.sbar-stat-v.b{color:var(--blu);}
.sbar-stat-l{font-size:8px;font-weight:700;color:var(--fa);text-transform:uppercase;letter-spacing:.7px;margin-top:2px;}
.sbar-div{width:1px;height:34px;background:var(--bd);}
.sbar-lv{background:linear-gradient(135deg,var(--poslt),var(--glt));border:1px solid var(--posmd);border-radius:var(--rpill);padding:6px 16px;font-size:11px;font-weight:800;color:var(--gdk);white-space:nowrap;}
.lvbar{background:var(--wh);border:1px solid var(--bd);border-radius:var(--rs);padding:10px 18px;margin-bottom:14px;display:flex;align-items:center;gap:14px;box-shadow:var(--sh);}
.lvbar-lbl{font-size:11px;font-weight:700;color:var(--mu);white-space:nowrap;}
.lvbar-track{flex:1;background:var(--bg);border-radius:99px;height:7px;overflow:hidden;}
.lvbar-fill{height:100%;background:linear-gradient(90deg,var(--g),var(--pos));border-radius:99px;transition:width .5s;}
.lvbar-pct{font-size:11px;font-weight:800;color:var(--gdk);font-family:'JetBrains Mono',monospace;white-space:nowrap;}
.lvbar-next{font-size:9px;color:var(--fa);white-space:nowrap;}
.sec-lbl{font-size:9px;font-weight:800;color:var(--mu);text-transform:uppercase;letter-spacing:1.2px;margin:16px 0 9px;display:flex;align-items:center;gap:7px;}
.sec-lbl::before{content:'🐾';font-size:10px;opacity:0.45;}
.sec-lbl::after{content:'';flex:1;height:1px;background:var(--bd);}
.sh3{display:flex;align-items:center;gap:9px;margin:18px 0 10px;}
.sh3-line{width:4px;height:16px;background:linear-gradient(180deg,var(--g),var(--pos));border-radius:2px;flex-shrink:0;}
.sh3-tit{font-size:13px;font-weight:800;color:var(--tx);}
.sh3-sub{font-size:10px;color:var(--mu);}
.mis-row{display:flex;gap:8px;margin-bottom:14px;}
.mis{flex:1;background:var(--wh);border:1px solid var(--bd);border-radius:13px;padding:13px 14px;box-shadow:var(--sh);position:relative;overflow:hidden;}
.mis::before{content:'🐾';position:absolute;bottom:-4px;right:4px;font-size:32px;opacity:0.06;pointer-events:none;}
.mis.dn{background:linear-gradient(135deg,var(--poslt),var(--glt));border-color:var(--posmd);}
.mis-top{display:flex;align-items:center;gap:8px;margin-bottom:8px;}
.mis-ico{font-size:16px;}
.mis-nm{font-size:11px;font-weight:700;color:var(--tx);}
.mis.dn .mis-nm{color:var(--gdk);}
.mis-bar{background:var(--bg);border-radius:99px;height:5px;overflow:hidden;margin-bottom:5px;}
.mis-fill{height:100%;background:linear-gradient(90deg,var(--g),var(--pos));border-radius:99px;transition:width .4s;}
.mis-ft{display:flex;justify-content:space-between;align-items:center;}
.mis-cur{font-size:9px;color:var(--mu);}
.mis-xp{font-size:9px;font-weight:800;color:var(--gdk);background:var(--poslt);border:1px solid var(--posmd);border-radius:var(--rpill);padding:1px 8px;font-family:'JetBrains Mono',monospace;}
.ac-wrap{border-radius:var(--r);overflow:hidden;box-shadow:var(--sh);margin-bottom:0;}
.ac-head{display:flex;align-items:stretch;border:1px solid var(--bd);border-radius:var(--r) var(--r) 0 0;overflow:hidden;}
.ac-bar{width:5px;flex-shrink:0;}
.ac-head-body{flex:1;display:flex;align-items:center;justify-content:space-between;padding:13px 16px;}
.ac-left{display:flex;align-items:center;gap:10px;}
.ac-ico-wrap{width:40px;height:40px;border-radius:11px;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;}
.ac-name{font-size:13px;font-weight:800;color:var(--tx);}
.ac-sub{font-size:10px;color:var(--mu);margin-top:2px;}
.ac-xp{font-size:26px;font-weight:900;font-family:'JetBrains Mono',monospace;line-height:1;}
.stForm{background:var(--wh)!important;border:1px solid var(--bd)!important;border-radius:0 0 var(--r) var(--r)!important;padding:15px 17px 17px!important;box-shadow:none!important;border-top:none!important;margin-top:0!important;}
.tl-card{background:var(--wh);border:1px solid var(--bd);border-radius:var(--r);padding:12px 15px;margin-bottom:8px;box-shadow:var(--sh);}
.tl-card-top{display:flex;align-items:flex-start;gap:10px;}
.tl-dot{width:8px;height:8px;border-radius:50%;background:var(--g);margin-top:3px;flex-shrink:0;}
.tl-dot.neg{background:var(--neg);}.tl-dot.blu{background:var(--blu);}
.tl-body{flex:1;min-width:0;}
.tl-nm{font-size:12px;font-weight:800;color:var(--tx);}
.tl-meta{font-size:10px;color:var(--mu);margin-top:1px;}
.tl-time-row{display:flex;align-items:center;gap:6px;margin-top:4px;flex-wrap:wrap;}
.tl-r{display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex-shrink:0;}
.tl-xp{font-size:10px;font-weight:800;font-family:'JetBrains Mono',monospace;color:var(--gdk);background:var(--poslt);border:1px solid var(--posmd);border-radius:var(--rpill);padding:1px 8px;white-space:nowrap;}
.tl-xp.neg{color:var(--neg);background:var(--neglt);border-color:var(--negmd);}
.sb-done{font-size:9px;font-weight:800;padding:2px 9px;border-radius:99px;background:var(--poslt);color:var(--posdk);border:1px solid var(--posmd);}
.sb-prog{font-size:9px;font-weight:800;padding:2px 9px;border-radius:99px;background:var(--bllt);color:var(--blu);border:1px solid var(--blmd);}
.sb-pend{font-size:9px;font-weight:800;padding:2px 9px;border-radius:99px;background:var(--urglt);color:var(--urg);border:1px solid var(--urgmd);}
.sb-canc{font-size:9px;font-weight:800;padding:2px 9px;border-radius:99px;background:var(--neglt);color:var(--neg);border:1px solid var(--negmd);}
.sb-pen{font-size:9px;font-weight:800;padding:2px 9px;border-radius:99px;background:var(--neglt);color:var(--neg);border:1px solid var(--negmd);}
.sb-oth{font-size:9px;font-weight:800;padding:2px 9px;border-radius:99px;background:var(--bg);color:var(--mu);border:1px solid var(--bd);}
.sb-qc-ok{font-size:9px;font-weight:800;padding:2px 9px;border-radius:99px;background:var(--poslt);color:var(--posdk);border:1px solid var(--posmd);}
.sb-qc-iss{font-size:9px;font-weight:800;padding:2px 9px;border-radius:99px;background:var(--neglt);color:var(--neg);border:1px solid var(--negmd);}
.sb-qc-pend{font-size:9px;font-weight:800;padding:2px 9px;border-radius:99px;background:var(--urglt);color:var(--urg);border:1px solid var(--urgmd);}
.sla-ok{font-size:9px;font-weight:800;padding:2px 8px;border-radius:99px;background:var(--poslt);color:var(--posdk);border:1px solid var(--posmd);}
.sla-warn{font-size:9px;font-weight:800;padding:2px 8px;border-radius:99px;background:var(--urglt);color:var(--urg);border:1px solid var(--urgmd);}
.sla-over{font-size:9px;font-weight:800;padding:2px 8px;border-radius:99px;background:var(--neglt);color:var(--neg);border:1px solid var(--negmd);}
.strip{border-radius:var(--rs);padding:9px 13px;margin-bottom:9px;font-size:11px;display:flex;align-items:center;gap:9px;line-height:1.5;font-weight:600;}
.strip.urg{background:var(--urglt);border:1px solid var(--urgmd);color:var(--urg);}
.strip.safe{background:var(--poslt);border:1px solid var(--posmd);color:var(--posdk);}
.strip.neut{background:var(--bg);border:1px dashed var(--bd);color:var(--mu);}
.strip.warn{background:#fff9f0;border:1px solid #f0c890;color:#8a5a00;}
.strip.info{background:var(--bllt);border:1px solid var(--blmd);color:var(--blu);}
.kpi-row{display:grid;grid-template-columns:repeat(5,1fr);gap:9px;margin-bottom:16px;}
.kpi-row-4{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-bottom:16px;}
.kpi-row-3{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-bottom:16px;}
.kpi{background:var(--wh);border:1px solid var(--bd);border-radius:var(--r);padding:16px 14px;text-align:center;box-shadow:var(--sh);position:relative;overflow:hidden;transition:transform .15s,box-shadow .15s;}
.kpi:hover{transform:translateY(-2px);box-shadow:var(--shm);}
.kpi::after{content:'🐾';position:absolute;bottom:-6px;right:-2px;font-size:36px;opacity:0.055;pointer-events:none;transform:rotate(20deg);}
.kpi::before{content:'';position:absolute;top:0;left:0;right:0;height:4px;border-radius:var(--r) var(--r) 0 0;}
.kpi.green::before{background:linear-gradient(90deg,var(--g),var(--pos));}
.kpi.red::before{background:linear-gradient(90deg,var(--neg),#f8b2b0);}
.kpi.yellow::before{background:linear-gradient(90deg,var(--urg),var(--urgmd));}
.kpi.blue::before{background:linear-gradient(90deg,var(--blu),#8fc0d0);}
.kpi.gray::before{background:var(--bd);}
.kpi-ico-wrap{width:38px;height:38px;border-radius:11px;display:flex;align-items:center;justify-content:center;font-size:17px;margin:0 auto 8px;}
.kpi.green .kpi-ico-wrap{background:var(--poslt);}
.kpi.red .kpi-ico-wrap{background:var(--neglt);}
.kpi.yellow .kpi-ico-wrap{background:var(--urglt);}
.kpi.blue .kpi-ico-wrap{background:var(--bllt);}
.kpi.gray .kpi-ico-wrap{background:var(--bg);}
.kpi-v{font-size:26px;font-weight:900;color:var(--tx);font-family:'JetBrains Mono',monospace;line-height:1;}
.kpi-v.g{color:var(--gdk);}.kpi-v.r{color:var(--neg);}.kpi-v.b{color:var(--blu);}
.kpi-lbl{font-size:9px;font-weight:700;color:var(--mu);margin-top:4px;text-transform:uppercase;letter-spacing:.4px;}
.sum-row{display:flex;gap:8px;margin-top:14px;}
.sum-item{flex:1;background:var(--bg);border:1px solid var(--bd);border-radius:var(--rs);padding:10px 12px;text-align:center;}
.sum-v{font-size:19px;font-weight:800;font-family:'JetBrains Mono',monospace;color:var(--tx);line-height:1;}
.sum-v.g{color:var(--gdk);}.sum-v.r{color:var(--neg);}.sum-v.b{color:var(--blu);}
.sum-l{font-size:8px;color:var(--mu);margin-top:3px;text-transform:uppercase;letter-spacing:.5px;font-weight:700;}
.lb{background:var(--wh);border:1px solid var(--bd);border-radius:var(--r);padding:12px 15px;margin-bottom:7px;display:flex;align-items:center;gap:12px;box-shadow:var(--sh);transition:box-shadow .15s,transform .15s;}
.lb:hover{box-shadow:var(--shm);transform:translateX(2px);}
.lb.r1{border-left:4px solid #c9a040;background:linear-gradient(135deg,#fffdf3,#fff);}
.lb.r2{border-left:4px solid #8f7872;}
.lb.r3{border-left:4px solid #a8a090;}
.lb-rk{font-size:15px;min-width:24px;text-align:center;font-weight:800;font-family:'JetBrains Mono',monospace;color:var(--fa);}
.lb-rk.g1{color:#c9a040;}.lb-rk.g2{color:#8f7872;}.lb-rk.g3{color:#a8a090;}
.lb-av{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:800;color:#fff;flex-shrink:0;}
.lb-info{flex:1;}
.lb-nm{font-size:12px;font-weight:800;color:var(--tx);}
.lb-dt{font-size:9px;color:var(--mu);margin-top:1px;}
.lb-bar{height:4px;background:var(--bg);border-radius:4px;margin-top:5px;overflow:hidden;}
.lb-fil{height:100%;background:linear-gradient(90deg,var(--g),var(--pos));border-radius:4px;}
.lb-rt{text-align:right;}
.lb-pt{font-size:18px;font-weight:800;font-family:'JetBrains Mono',monospace;}
.lb-lv{font-size:9px;font-weight:700;background:var(--poslt);border:1px solid var(--posmd);border-radius:var(--rpill);padding:2px 9px;display:inline-block;margin-top:3px;color:var(--posdk);}
.lb-neg{font-size:9px;font-weight:700;color:var(--neg);font-family:'JetBrains Mono',monospace;}
.qc-item{background:var(--wh);border:1px solid var(--bd);border-radius:var(--r);padding:14px 16px;margin-bottom:9px;box-shadow:var(--sh);transition:box-shadow .15s;}
.qc-item:hover{box-shadow:var(--shm);}
.qc-item.needs-qc{border-left:4px solid var(--urg);}
.qc-item.has-issue{border-left:4px solid var(--neg);}
.qc-item.ok{border-left:4px solid var(--g);}
.qc-top{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:9px;}
.qc-id{font-size:12px;font-weight:800;color:var(--tx);}
.qc-meta{font-size:10px;color:var(--mu);margin-top:2px;}
.qc-badges{display:flex;gap:5px;flex-wrap:wrap;}
.notif{border-radius:var(--r);padding:12px 16px;margin-bottom:14px;display:flex;align-items:flex-start;gap:12px;border:1px solid;}
.notif.dn{background:var(--neglt);border-color:var(--negmd);}
.notif.ok{background:var(--poslt);border-color:var(--posmd);}
.notif.info{background:var(--bllt);border-color:var(--blmd);}
.ni{font-size:20px;flex-shrink:0;line-height:1.4;}
.nb{flex:1;}
.nt{font-size:12px;font-weight:800;margin-bottom:2px;}
.notif.dn .nt{color:var(--neg);}.notif.ok .nt{color:var(--posdk);}.notif.info .nt{color:var(--blu);}
.nd{font-size:11px;color:var(--mu);margin-bottom:5px;}
.pills{display:flex;flex-wrap:wrap;gap:5px;}
.pill{font-size:10px;font-weight:700;padding:2px 9px;border-radius:var(--rpill);background:var(--neglt);color:var(--neg);border:1px solid var(--negmd);}
.div{height:1px;background:var(--bd);margin:16px 0;}
.pt-row{display:flex;align-items:center;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--bd);}
.pt-row:last-child{border-bottom:none;}
.pt-n{font-size:11px;color:var(--tx)!important;font-weight:600;}
.pt-p{font-family:'JetBrains Mono',monospace;font-weight:800;font-size:11px;color:var(--gdk)!important;}
.pt-p.neg{color:var(--neg)!important;}
.page-header{border-radius:var(--r);padding:20px 26px;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;position:relative;overflow:hidden;}
.page-header::after{content:'🐾';position:absolute;right:120px;top:50%;transform:translateY(-50%) rotate(25deg);font-size:80px;opacity:0.07;pointer-events:none;}
.ph-inner{position:relative;z-index:1;}
.ph-label{font-size:9px;font-weight:700;color:rgba(255,255,255,0.5);text-transform:uppercase;letter-spacing:1.6px;margin-bottom:4px;}
.ph-title{font-size:21px;font-weight:900;color:#fff;letter-spacing:-.4px;}
.ph-sub{font-size:11px;color:rgba(255,255,255,0.55);margin-top:3px;}
.ph-badge{background:rgba(255,255,255,0.18);border-radius:12px;padding:11px 20px;text-align:center;position:relative;z-index:1;backdrop-filter:blur(6px);}
.ph-badge-v{font-size:26px;font-weight:900;color:#fff;font-family:'JetBrains Mono',monospace;line-height:1;}
.ph-badge-l{font-size:8px;color:rgba(255,255,255,0.55);text-transform:uppercase;letter-spacing:1px;margin-top:2px;}
.stSelectbox>div>div,.stTextInput>div>div>input,.stTextArea>div>div>textarea,.stDateInput>div>div>input{background:var(--bg)!important;border:1.5px solid var(--bd)!important;border-radius:var(--rs)!important;color:var(--tx)!important;font-family:'Nunito',sans-serif!important;font-size:13px!important;font-weight:600!important;transition:all .15s!important;}
.stSelectbox>div>div:focus-within,.stTextInput>div>div>input:focus,.stTextArea>div>div>textarea:focus{border-color:var(--g)!important;box-shadow:0 0 0 3px rgba(60,174,80,0.14)!important;background:var(--wh)!important;}
label[data-testid="stWidgetLabel"]>div>p,.stDateInput label,.stSelectbox label,.stTextInput label,.stTextArea label{color:var(--mu)!important;font-size:10px!important;font-weight:800!important;text-transform:uppercase!important;letter-spacing:.8px!important;}
.stButton>button{background:var(--wh)!important;color:var(--gdk)!important;border:1.5px solid var(--gmd)!important;border-radius:var(--rs)!important;font-family:'Nunito',sans-serif!important;font-weight:800!important;font-size:13px!important;padding:9px 18px!important;width:100%!important;transition:all .15s!important;}
.stButton>button:hover{background:var(--glt)!important;border-color:var(--g)!important;transform:translateY(-1px)!important;}
.stFormSubmitButton>button{background:linear-gradient(135deg,var(--g),var(--g2))!important;color:#fff!important;border:none!important;width:100%!important;padding:14px!important;font-size:14px!important;font-weight:900!important;border-radius:var(--r)!important;font-family:'Nunito',sans-serif!important;box-shadow:0 4px 16px rgba(60,174,80,0.30)!important;transition:all .2s!important;letter-spacing:.2px!important;}
.stFormSubmitButton>button:hover{background:linear-gradient(135deg,var(--gdk),var(--g))!important;transform:translateY(-2px)!important;box-shadow:0 8px 24px rgba(60,174,80,0.36)!important;}
.stSuccess{background:var(--poslt)!important;border:1px solid var(--posmd)!important;border-radius:var(--rs)!important;}
.stWarning{background:var(--urglt)!important;border:1px solid var(--urgmd)!important;border-radius:var(--rs)!important;}
.stError{background:var(--neglt)!important;border:1px solid var(--negmd)!important;border-radius:var(--rs)!important;}
.stDownloadButton>button{background:var(--wh)!important;color:var(--gdk)!important;border:1.5px solid var(--g)!important;width:auto!important;font-weight:800!important;font-size:12px!important;}
.stDataFrame{border:1px solid var(--bd)!important;border-radius:var(--rs)!important;}
hr{border-color:var(--bd)!important;margin:14px 0!important;}
::-webkit-scrollbar{width:4px;height:4px;}
::-webkit-scrollbar-thumb{background:var(--gmd);border-radius:2px;}
[data-testid="stTabs"] [role="tablist"]{border-bottom:1px solid var(--bd)!important;}
[data-testid="stTabs"] button[role="tab"]{font-family:'Nunito',sans-serif!important;font-size:12px!important;font-weight:700!important;color:var(--mu)!important;border:none!important;padding:8px 16px!important;}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"]{color:var(--gdk)!important;border-bottom:3px solid var(--g)!important;font-weight:900!important;}
/* idle toast */
#idle-toast{position:fixed;bottom:18px;right:18px;background:#2c2825;color:#fff;font-family:'Nunito',sans-serif;font-size:11px;font-weight:700;padding:8px 14px;border-radius:10px;display:flex;align-items:center;gap:8px;z-index:99998;opacity:0;transition:opacity .3s;pointer-events:none;box-shadow:0 4px 16px rgba(0,0,0,0.18);}
#idle-toast.show{opacity:1;}
#idle-dot{width:8px;height:8px;border-radius:50%;background:#88bc77;flex-shrink:0;animation:idle-pulse 2s infinite;}
#idle-dot.warn{background:#f0a040;}
#idle-dot.danger{background:#f8b2b0;}
@keyframes idle-pulse{0%,100%{opacity:1}50%{opacity:.4}}
</style>
"""

LOGIN_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;500;600;700;800;900&display=swap');
section[data-testid="stSidebar"],[data-testid="stHeader"],[data-testid="stToolbar"],footer{display:none!important;}
html,body{background:#f5f0ec!important;min-height:100vh!important;margin:0!important;padding:0!important;}
.stApp,[data-testid="stAppViewContainer"],.stApp>div,[data-testid="stVerticalBlock"]{background:transparent!important;}
[data-testid="stForm"]{background:transparent!important;border:none!important;padding:0!important;box-shadow:none!important;}
label[data-testid="stWidgetLabel"]>div>p{display:none!important;}
.block-container{padding:0!important;max-width:100%!important;}
[data-testid="stAppViewBlockContainer"]{padding:0!important;}
body::before{content:'';position:fixed;inset:0;background:radial-gradient(ellipse at 20% 20%,#cfe5a460 0%,transparent 55%),radial-gradient(ellipse at 80% 80%,#f8b2b035 0%,transparent 55%),radial-gradient(ellipse at 50% 100%,#3cae5020 0%,transparent 50%),linear-gradient(160deg,#faf8f6 0%,#f0ece6 60%,#e8e4de 100%);pointer-events:none;z-index:0;}
body::after{content:'🐾';position:fixed;font-size:120px;opacity:0.04;bottom:30px;left:30px;transform:rotate(-20deg);pointer-events:none;z-index:0;animation:paw-drift 6s ease-in-out infinite;}
@keyframes paw-drift{0%,100%{transform:rotate(-20deg) translateY(0)}50%{transform:rotate(-20deg) translateY(-12px)}}
.lc-paw1{position:fixed;top:12%;right:8%;font-size:72px;opacity:0.05;transform:rotate(30deg);pointer-events:none;z-index:0;animation:paw-drift 5s 1s ease-in-out infinite;}
.lc-paw2{position:fixed;top:60%;left:6%;font-size:54px;opacity:0.04;transform:rotate(-10deg);pointer-events:none;z-index:0;animation:paw-drift 7s 2s ease-in-out infinite;}
.lc-paw3{position:fixed;top:5%;left:30%;font-size:40px;opacity:0.035;transform:rotate(15deg);pointer-events:none;z-index:0;animation:paw-drift 8s 3s ease-in-out infinite;}
.lc-col>[data-testid="stVerticalBlock"]{background:rgba(255,255,255,0.88)!important;border:1px solid rgba(255,255,255,0.98)!important;border-radius:22px!important;box-shadow:0 12px 40px rgba(44,40,37,0.10),0 2px 8px rgba(60,174,80,0.10),inset 0 1px 0 #fff!important;backdrop-filter:blur(28px)!important;-webkit-backdrop-filter:blur(28px)!important;overflow:hidden!important;}
.lc-col>[data-testid="stVerticalBlock"] [data-testid="stVerticalBlock"]{background:transparent!important;border:none!important;border-radius:0!important;box-shadow:none!important;backdrop-filter:none!important;overflow:visible!important;}
.lc-head{display:flex;align-items:center;justify-content:space-between;padding:20px 20px 0;margin-bottom:12px;}
.lc-brand{display:flex;align-items:center;gap:11px;}
.lc-logo{width:42px;height:42px;background:linear-gradient(135deg,#1e7a32,#88bc77);border-radius:13px;display:flex;align-items:center;justify-content:center;font-size:20px;box-shadow:0 4px 12px rgba(60,174,80,0.30);flex-shrink:0;position:relative;overflow:hidden;}
.lc-logo::after{content:'🐾';position:absolute;bottom:-4px;right:-4px;font-size:18px;opacity:0.3;}
.lc-title{font-size:16px;font-weight:900;color:#2c2825;letter-spacing:-.4px;font-family:'Nunito',sans-serif;}
.lc-subtitle{font-size:9px;color:#8f7872;margin-top:1px;font-family:'Nunito',sans-serif;font-weight:600;text-transform:uppercase;letter-spacing:.8px;}
.lc-online{display:flex;align-items:center;gap:5px;background:rgba(207,229,164,0.55);border:1px solid #b8d98e;border-radius:99px;padding:4px 10px;font-size:9px;font-weight:800;color:#3a6010;white-space:nowrap;}
.lc-dot{width:6px;height:6px;background:#88bc77;border-radius:50%;animation:lc-p 2s infinite;flex-shrink:0;}
@keyframes lc-p{0%,100%{opacity:1}50%{opacity:.3}}
.lc-sep{height:1px;background:linear-gradient(90deg,transparent,rgba(60,174,80,0.20),transparent);margin:0 20px 14px;}
.lc-cats{display:flex;justify-content:center;gap:8px;padding:8px 20px 0;margin-bottom:-4px;}
.lc-cat-ico{font-size:22px;opacity:0.65;animation:paw-drift 3s ease-in-out infinite;}
.lc-cat-ico:nth-child(2){animation-delay:.6s;}
.lc-cat-ico:nth-child(3){animation-delay:1.2s;}
.lc-form{padding:0 20px 18px;}
.lc-lbl{font-size:9px;font-weight:800;color:#8f7872;text-transform:uppercase;letter-spacing:1.2px;margin-bottom:4px;font-family:'Nunito',sans-serif;display:block;}
.stSelectbox>div>div{background:rgba(250,248,246,0.92)!important;border:1.5px solid rgba(143,120,114,0.28)!important;border-radius:11px!important;font-family:'Nunito',sans-serif!important;font-size:13px!important;font-weight:600!important;}
.stSelectbox>div>div:focus-within{border-color:#88bc77!important;box-shadow:0 0 0 3px rgba(60,174,80,0.14)!important;}
.stTextInput>div>div>input{background:rgba(250,248,246,0.92)!important;border:1.5px solid rgba(143,120,114,0.28)!important;border-radius:11px!important;font-family:'Nunito',sans-serif!important;font-size:13px!important;font-weight:600!important;padding:10px 13px!important;color:#2c2825!important;}
.stTextInput>div>div>input:focus{border-color:#88bc77!important;box-shadow:0 0 0 3px rgba(60,174,80,0.14)!important;background:#fff!important;}
.stTextInput>div>div>input::placeholder{color:#b0a49e!important;}
.stFormSubmitButton>button{background:linear-gradient(135deg,#1e7a32,#88bc77)!important;color:#fff!important;border:none!important;border-radius:12px!important;padding:13px!important;font-size:14px!important;font-weight:900!important;font-family:'Nunito',sans-serif!important;width:100%!important;box-shadow:0 5px 18px rgba(60,174,80,0.28)!important;transition:all .18s!important;margin-top:4px!important;letter-spacing:.2px!important;}
.stFormSubmitButton>button:hover{transform:translateY(-2px)!important;box-shadow:0 8px 26px rgba(60,174,80,0.36)!important;}
.stFormSubmitButton>button::before{content:'🐾  ';}
.lc-paw-sep{text-align:center;font-size:13px;letter-spacing:6px;opacity:0.25;margin:4px 20px 10px;color:#8f7872;}
.lc-err{display:flex;align-items:center;gap:8px;background:#fef0ef;border:1px solid #f8b2b0;border-radius:11px;padding:9px 13px;font-size:11px;font-weight:700;color:#c0392b;margin:8px 20px 0;}
.lc-ft{text-align:center;font-size:8px;color:#b0a49e;margin:10px 20px 18px;letter-spacing:.5px;font-weight:600;}
[data-testid="stHorizontalBlock"]{gap:0!important;}
[data-testid="stColumn"]{padding:0!important;}
</style>
<div class="lc-paw1">🐾</div>
<div class="lc-paw2">🐾</div>
<div class="lc-paw3">🐾</div>
"""

# ── Idle JS ───────────────────────────────────────────────────────────────────
IDLE_JS = f"""
<div id="idle-toast"><div id="idle-dot"></div><span id="idle-txt">Sesi aktif</span></div>
<script>
(function(){{
  var TIMEOUT={IDLE_TIMEOUT_MS};
  var WARN_AT=TIMEOUT-2*60*1000;
  var lastAct=Date.now();
  var toast=document.getElementById('idle-toast');
  var dot=document.getElementById('idle-dot');
  var txt=document.getElementById('idle-txt');
  ['mousemove','keydown','mousedown','touchstart','scroll','click'].forEach(function(ev){{
    document.addEventListener(ev,function(){{lastAct=Date.now();}},{{passive:true}});
  }});
  function fmt(ms){{
    var s=Math.ceil(ms/1000);
    var m=Math.floor(s/60);
    var ss=s%60;
    return m+'m '+(ss<10?'0':'')+ss+'s';
  }}
  setInterval(function(){{
    var elapsed=Date.now()-lastAct;
    var sisa=TIMEOUT-elapsed;
    if(sisa<=0){{window.location.reload();return;}}
    if(elapsed>=WARN_AT){{
      toast.classList.add('show');
      if(sisa<=60000){{dot.className='danger';txt.textContent='Logout otomatis: '+fmt(sisa);}}
      else{{dot.className='warn';txt.textContent='Idle - Logout dalam '+fmt(sisa);}}
    }}else{{
      toast.classList.remove('show');
      dot.className='';
      txt.textContent='Sesi aktif';
    }}
  }},1000);
}})();
</script>
"""

# ── Google Sheets ─────────────────────────────────────────────────────────────
@st.cache_resource(ttl=3600)
def _get_or_create_ws(_wb, name, rows, cols):
    try:
        return _wb.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        return _wb.add_worksheet(title=name, rows=rows, cols=cols)

@st.cache_resource(ttl=3600)
def get_sheets():
    try:
        scope  = ["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
        creds  = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        wb     = client.open_by_key(SHEET_ID)
        def _init(name, rows, cols, headers):
            ws = _get_or_create_ws(wb, name, rows, cols)
            if not ws.row_values(1) or ws.row_values(1) != headers:
                ws.clear(); ws.insert_row(headers, 1)
            return ws
        ws1 = _init("Task Log",   1000, 20, HEADERS)
        ws2 = _init("QC Log",      500, 12, QC_HEADERS)
        ws3 = _init("Session Log", 500, 10, SESSION_HEADERS)
        ws4 = _init("QC Score",    100,  8, QC_SCORE_HEADERS)
        return ws1, ws2, ws3, ws4, None
    except Exception as exc:
        return None, None, None, None, str(exc)

@st.cache_data(ttl=120)
def load_data():
    ws1, ws2, ws3, ws4, _ = get_sheets()
    if ws1 is None:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    try:
        return (
            pd.DataFrame(ws1.get_all_records()),
            pd.DataFrame(ws2.get_all_records()) if ws2 else pd.DataFrame(),
            pd.DataFrame(ws3.get_all_records()) if ws3 else pd.DataFrame(),
            pd.DataFrame(ws4.get_all_records()) if ws4 else pd.DataFrame(),
        )
    except Exception:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# ── XP / Level Helpers ────────────────────────────────────────────────────────
def is_penalty(task_type): return task_type in PENALTY_TYPES

def calc_xp(task_type, status):
    if is_penalty(task_type): return PENALTY_TYPES[task_type][2]
    base = TASK_TYPES.get(task_type, ("","",10,""))[2]
    return base + (DONE_BONUS if str(status).lower() == "done" else 0)

def calc_xp_df(df):
    if df.empty: return 0
    if "Poin" in df.columns:
        try: return int(df["Poin"].sum())
        except: pass
    return sum(calc_xp(r.get("Task Type",""), r.get("Status","")) for _, r in df.iterrows())

def calc_penalty_df(df):
    if df.empty or "Task Type" not in df.columns: return 0
    return sum(int(r.get("Poin", PENALTY_TYPES[r["Task Type"]][2])) for _, r in df.iterrows() if r.get("Task Type","") in PENALTY_TYPES)

def get_level(xp):
    current = LEVELS[0]
    for threshold, name in LEVELS:
        if xp >= threshold: current = (threshold, name)
    idx = next(i for i,(t,_) in enumerate(LEVELS) if t == current[0])
    nxt = LEVELS[idx+1][0] if idx+1 < len(LEVELS) else LEVELS[-1][0]
    return current[1], current[0], nxt

def xp_percent(xp, min_xp, max_xp):
    if max_xp == min_xp: return 100
    return min(100, int((xp-min_xp)/(max_xp-min_xp)*100))

# ── QC Score Helpers ──────────────────────────────────────────────────────────
def get_qc_score(qc_score_df, staff):
    if qc_score_df.empty or "Staff" not in qc_score_df.columns: return 0,0,0,100
    row = qc_score_df[qc_score_df["Staff"]==staff]
    if row.empty: return 0,0,0,100
    r = row.iloc[0]
    return int(r.get("Total QC",0) or 0), int(r.get("Correct",0) or 0), int(r.get("Miss",0) or 0), int(r.get("Accuracy",100) or 100)

def _now_jkt_str(): return datetime.now(TZ_JKT).strftime("%Y-%m-%d %H:%M:%S")

def update_qc_score(ws4, qc_score_df, staff, found_issue):
    now_str = _now_jkt_str()
    try:
        if ws4 is None: return
        match = qc_score_df[qc_score_df["Staff"]==staff] if not qc_score_df.empty and "Staff" in qc_score_df.columns else pd.DataFrame()
        if not match.empty:
            r=match.iloc[0]; row_idx=match.index[0]+2
            total=int(r.get("Total QC",0) or 0)+1; correct=int(r.get("Correct",0) or 0)+1
            miss=int(r.get("Miss",0) or 0); acc=int(correct/total*100) if total>0 else 100
            ws4.update(f"A{row_idx}:F{row_idx}",[[staff,total,correct,miss,acc,now_str]])
        else:
            ws4.append_row([staff,1,1,0,100,now_str])
    except: pass

# ── Mission Helpers ───────────────────────────────────────────────────────────
def missions_booker(tasks):
    total=len(tasks); done=len(tasks[tasks["Status"]=="Done"]) if not tasks.empty and "Status" in tasks.columns else 0
    urgent=len(tasks[tasks["Task Type"]=="Booking Urgent"]) if not tasks.empty and "Task Type" in tasks.columns else 0
    return [
        {"ico":"📋","nm":"5 Task","cur":min(total,5),"tgt":5,"xp":50,"done":total>=5},
        {"ico":"✅","nm":"3 Done","cur":min(done,3),"tgt":3,"xp":40,"done":done>=3},
        {"ico":"⚡","nm":"1 Urgent","cur":min(urgent,1),"tgt":1,"xp":30,"done":urgent>=1},
    ]

def missions_finance(qc_df, staff):
    done=0
    if not qc_df.empty and "QC By" in qc_df.columns:
        done=len(qc_df[(qc_df["QC By"]==staff)&(qc_df["Date"]==datetime.now().strftime("%Y-%m-%d"))])
    return [
        {"ico":"🔍","nm":"QC 3 Transaksi","cur":min(done,3),"tgt":3,"xp":60,"done":done>=3},
        {"ico":"🎯","nm":"QC 5 Transaksi","cur":min(done,5),"tgt":5,"xp":80,"done":done>=5},
        {"ico":"⭐","nm":"QC 10 Transaksi","cur":min(done,10),"tgt":10,"xp":120,"done":done>=10},
    ]

# ── HTML Builders ─────────────────────────────────────────────────────────────
def status_badge(status, task_type=""):
    if task_type in PENALTY_TYPES: return '<span class="sb-pen">Penalti</span>'
    s=str(status).lower()
    if s=="done": return f'<span class="sb-done">{status}</span>'
    if "progress" in s: return f'<span class="sb-prog">{status}</span>'
    if "pending" in s or "waiting" in s or "hold" in s: return f'<span class="sb-pend">{status}</span>'
    if "cancel" in s: return f'<span class="sb-canc">{status}</span>'
    return f'<span class="sb-oth">{status}</span>'

def qc_badge(qc_status):
    s=str(qc_status).lower()
    if "ok" in s: return "sb-qc-ok"
    if "isu" in s: return "sb-qc-iss"
    return "sb-qc-pend"

def sla_badge(minutes):
    try:
        m=float(minutes)
        if m<=SLA_TARGET: return "sla-ok", f"{int(m)}m"
        elif m<=SLA_TARGET*1.5: return "sla-warn", f"{int(m)}m ⚠"
        else: return "sla-over", f"{int(m)}m ❌"
    except: return "sla-ok","-"

def rank_class(rank): return {1:"g1",2:"g2",3:"g3"}.get(rank,"")
def card_class(rank): return {1:"r1",2:"r2",3:"r3"}.get(rank,"")
def rank_emoji(rank): return {1:"🥇",2:"🥈",3:"🥉"}.get(rank,f"#{rank}")

def section_header(title, subtitle=""):
    sub = f'<div class="sh3-sub">{subtitle}</div>' if subtitle else ""
    return f'<div class="sh3"><div class="sh3-line"></div><div><div class="sh3-tit">{title}</div>{sub}</div></div>'

def kpi_card(icon, value, label, variant="green"):
    ico_bg={"green":"var(--glt)","red":"var(--neglt)","yellow":"var(--urglt)","blue":"var(--bllt)","gray":"var(--bg)"}
    return (f'<div class="kpi {variant}"><div class="kpi-ico-wrap" style="background:{ico_bg.get(variant,"var(--glt)")}">{icon}</div>'
            f'<div class="kpi-v">{value}</div><div class="kpi-lbl">{label}</div></div>')

def missions_html(missions, accent="var(--g)"):
    items=[]
    for m in missions:
        pct=int(m["cur"]/m["tgt"]*100); cls=" dn" if m["done"] else ""
        fill_style=f'style="background:{accent};width:{pct}%"' if accent!="var(--g)" else f'style="width:{pct}%"'
        xp_style=f'style="color:{accent};background:var(--bllt);border-color:var(--blmd)"' if accent!="var(--g)" else ""
        items.append(f'<div class="mis{cls}"><div class="mis-top"><span class="mis-ico">{m["ico"]}</span><span class="mis-nm">{m["nm"]}</span></div>'
                     f'<div class="mis-bar"><div class="mis-fill" {fill_style}></div></div>'
                     f'<div class="mis-ft"><span class="mis-cur">{m["cur"]}/{m["tgt"]}</span>'
                     f'<span class="mis-xp" {xp_style}>+{m["xp"]}</span></div></div>')
    return '<div class="mis-row">'+"".join(items)+"</div>"

def plotly_layout_base(height=200, margin=None):
    return {"paper_bgcolor":"rgba(0,0,0,0)","plot_bgcolor":"rgba(0,0,0,0)","font":{"color":"#777","family":"Inter"},"margin":margin or {"l":0,"r":0,"t":4,"b":0},"height":height}

# ── Session / Idle Helpers ────────────────────────────────────────────────────
def parse_jkt(ts_str):
    try:
        clean=str(ts_str).replace(" WIB","").strip()
        dt=datetime.strptime(clean,"%Y-%m-%d %H:%M:%S")
        return TZ_JKT.localize(dt)
    except: return None

def format_duration(minutes):
    h,m=divmod(minutes,60)
    return f"{h}j {m}m" if h>0 else f"{m}m"

def get_absent_staff(df, today_str):
    flat=ALL_STAFF["Finance"]+ALL_STAFF["Booker"]
    if df.empty or "Staff" not in df.columns: return flat
    present=df[df["Date"]==today_str]["Staff"].unique().tolist()
    return [s for s in flat if s not in present]

def update_activity():
    st.session_state.last_activity = datetime.now(TZ_JKT)

def check_idle_timeout():
    if not st.session_state.get("logged_in"): return False
    last = st.session_state.get("last_activity")
    if last is None:
        update_activity(); return False
    elapsed = (datetime.now(TZ_JKT) - last).total_seconds() / 60
    if elapsed >= IDLE_TIMEOUT_MINUTES:
        _do_auto_logout(); return True
    return False

def _do_auto_logout():
    try:
        nj_out = datetime.now(TZ_JKT)
        out_ts = nj_out.strftime("%Y-%m-%d %H:%M:%S") + " WIB"
        if st.session_state.get("login_time") and st.session_state.get("session_row"):
            dur = int((nj_out - st.session_state.login_time).total_seconds() / 60)
            _, _, _ws3, _, _ = get_sheets()
            if _ws3:
                row = st.session_state.session_row
                _ws3.update_cell(row, 5, out_ts)
                _ws3.update_cell(row, 6, dur)
                _ws3.update_cell(row, 7, "Auto-Logout")
    except:
        pass
    st.session_state.update({
        "logged_in":       False,
        "current_user":    "",
        "current_role":    "",
        "login_time":      None,
        "session_row":     None,
        "last_activity":   None,
        "auto_logout_msg": True,
    })
    st.query_params.clear()

# ── Session State Init ────────────────────────────────────────────────────────
_DEFAULTS = {
    "logged_in":        False,
    "current_user":     "",
    "current_role":     "",
    "pw_error":         False,
    "login_time":       None,
    "session_row":      None,
    "qc_locked_task":   None,
    "level_up_pending": None,
    "last_activity":    None,
    "auto_logout_msg":  False,
}
for _k,_v in _DEFAULTS.items():
    if _k not in st.session_state: st.session_state[_k]=_v

# ── Restore dari query params ─────────────────────────────────────────────────
_qp=st.query_params
if not st.session_state.logged_in and "u" in _qp and "r" in _qp:
    _user,_role=_qp["u"],_qp["r"]
    if _user in PASSWORDS and _role in ROLES:
        st.session_state.logged_in=True
        st.session_state.current_user=_user
        st.session_state.current_role=_role

if check_idle_timeout():
    st.rerun()

if st.session_state.logged_in and st.session_state.last_activity is None:
    update_activity()

# ── Data Loading ──────────────────────────────────────────────────────────────
ws1, ws2, ws3, ws4, sheet_err = get_sheets()
df, qc_df, session_df, qc_score_df = load_data()
today_str = datetime.now().strftime("%Y-%m-%d")
today_df = (
    df[df["Date"] == today_str]
    if not df.empty and "Date" in df.columns
    else pd.DataFrame()
)

# ── CSS Injection ─────────────────────────────────────────────────────────────
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
if st.session_state.logged_in:
    st.markdown(IDLE_JS, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  LOGIN PAGE
# ══════════════════════════════════════════════════════════════════════════════
if not st.session_state.logged_in:
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)

    if st.session_state.get("auto_logout_msg"):
        st.session_state.auto_logout_msg = False
        st.markdown(
            '<div style="background:#fef8ec;border:1px solid #f9e2b2;border-radius:11px;'
            'padding:10px 14px;margin:0 auto 12px;max-width:360px;font-size:11px;'
            'font-weight:700;color:#8a5a00;text-align:center;">'
            '⏰ Sesi berakhir karena tidak ada aktivitas selama 15 menit.</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div style="display:block;height:calc(50vh - 240px);min-height:16px"></div>', unsafe_allow_html=True)

    _, col_mid, _ = st.columns([1,1,1])
    with col_mid:
        st.markdown('<div class="lc-col">', unsafe_allow_html=True)
        st.markdown(
            '<div class="lc-head"><div class="lc-brand">'
            '<div class="lc-logo">🐾</div>'
            '<div><div class="lc-title">Pawgress</div>'
            '<div class="lc-subtitle">Reservation · Quality Control</div></div>'
            '</div><div class="lc-online"><div class="lc-dot"></div>Online</div></div>'
            '<div class="lc-sep"></div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="lc-cats"><span class="lc-cat-ico">🐱</span><span class="lc-cat-ico">🐾</span><span class="lc-cat-ico">🐈</span></div>', unsafe_allow_html=True)
        st.markdown('<div class="lc-form">', unsafe_allow_html=True)
        with st.form("login_form", clear_on_submit=False):
            st.markdown('<span class="lc-lbl">Nama</span>', unsafe_allow_html=True)
            staff_sel=st.selectbox("Nama", ALL_STAFF_FLAT, label_visibility="collapsed", key="ls_main")
            st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
            st.markdown('<span class="lc-lbl">Password</span>', unsafe_allow_html=True)
            pw=st.text_input("Password", type="password", placeholder="Masukkan password...", label_visibility="collapsed", key="lp_main")
            st.markdown('<div class="lc-paw-sep">🐾 🐾 🐾</div>', unsafe_allow_html=True)
            submitted=st.form_submit_button("Masuk  →", use_container_width=True)
            if submitted:
                if pw and pw==PASSWORDS.get(staff_sel,""):
                    detected_role=STAFF_ROLE_MAP.get(staff_sel,"Booker")
                    nj_login=datetime.now(TZ_JKT)
                    login_ts=nj_login.strftime("%Y-%m-%d %H:%M:%S")+" WIB"
                    st.session_state.update({
                        "logged_in":True,"current_user":staff_sel,"current_role":detected_role,
                        "pw_error":False,"login_time":nj_login,"last_activity":datetime.now(TZ_JKT),
                    })
                    st.query_params["u"]=staff_sel; st.query_params["r"]=detected_role
                    try:
                        _,_,_ws3,_,_=get_sheets()
                        if _ws3:
                            _ws3.append_row([nj_login.strftime("%Y-%m-%d"),staff_sel,detected_role,login_ts,"","","Online"])
                            st.session_state.session_row=None
                    except: pass
                    st.rerun()
                else:
                    st.session_state.pw_error=True; st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        if st.session_state.pw_error:
            st.markdown('<div class="lc-err">❌&nbsp; Password salah, coba lagi.</div>', unsafe_allow_html=True)
        st.markdown('<div class="lc-ft">© 2026 Pawgress · QC Dashboard v2.0</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════════════════════════════════
sel=st.session_state.current_user
user_role=st.session_state.current_role
role_cfg=ROLES[user_role]

my_all=df[df["Staff"]==sel] if not df.empty and "Staff" in df.columns else pd.DataFrame()
my_today=today_df[today_df["Staff"]==sel] if not today_df.empty and "Staff" in today_df.columns else pd.DataFrame()
my_tasks=(my_today[~my_today["Task Type"].isin(PENALTY_TYPES.keys())] if not my_today.empty and "Task Type" in my_today.columns else my_today)
my_penalties=(my_today[my_today["Task Type"].isin(PENALTY_TYPES.keys())] if not my_today.empty and "Task Type" in my_today.columns else pd.DataFrame())

xp_all=calc_xp_df(my_all); xp_today=calc_xp_df(my_tasks)
pen_today=calc_penalty_df(my_penalties); net_today=xp_today+pen_today
level_name,level_min,level_max=get_level(max(xp_all,0))
level_pct=xp_percent(xp_all,level_min,level_max)
done_today=(len(my_tasks[my_tasks["Status"]=="Done"]) if not my_tasks.empty and "Status" in my_tasks.columns else 0)
initials=sel[:2].upper()
now_hour=datetime.now().hour
greeting="Pagi ☀️" if now_hour<11 else "Siang 🌤️" if now_hour<15 else "Sore 🌅" if now_hour<18 else "Malam 🌃"
team_xp=calc_xp_df(today_df)
my_qc_today=pd.DataFrame()
if not qc_df.empty and "QC By" in qc_df.columns and "Date" in qc_df.columns:
    my_qc_today=qc_df[(qc_df["QC By"]==sel)&(qc_df["Date"]==today_str)]

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="sb-head"><div class="sb-head-inner"><div class="sb-ico">🐾</div><div><div class="sb-title">Pawgress</div><div class="sb-sub">Dashboard</div></div></div></div>', unsafe_allow_html=True)
    conn_html=('<div style="background:#fdf2f1;border:1px solid #f0a49d;border-radius:8px;padding:7px 12px;margin:8px 12px;font-size:10px;color:#c0392b;font-weight:600">⚠️ Sheets tidak terhubung</div>' if sheet_err else
               '<div style="background:#e8f8eb;border:1px solid #96d8a0;border-radius:8px;padding:7px 12px;margin:8px 12px;font-size:10px;color:#1e7a32;font-weight:600">✅ Google Sheets terhubung</div>')
    st.markdown(conn_html, unsafe_allow_html=True)
    st.markdown(f'<div class="role-chip rc-{user_role.lower()}"><div class="rc-dot"></div>{role_cfg["emoji"]} {user_role} — {sel}</div>', unsafe_allow_html=True)
    st.markdown('<div class="sb-lbl">Menu</div>', unsafe_allow_html=True)
    menu_options={"Manager":["📊  Manager Dashboard","🔍  QC Monitor","🏆  Leaderboard","🕐  Session Monitor"],"Finance":["✏️  Input Task","🔍  QC Silang","📊  Dashboard Saya"],"Booker":["✏️  Input Task","🔍  QC Silang","📊  Dashboard Saya"]}
    menu=st.selectbox("Menu", menu_options[user_role], label_visibility="collapsed")
    absent_count=len(get_absent_staff(df,today_str))
    absent_cls="y" if absent_count>0 else "g"
    qc_done_today=len(my_qc_today) if not my_qc_today.empty else 0
    st.markdown(f'<div class="sb-stat-grid"><div class="sb-stat"><div class="sb-stat-v">{len(my_tasks)}</div><div class="sb-stat-l">Task Ku</div></div><div class="sb-stat"><div class="sb-stat-v g">{net_today}</div><div class="sb-stat-l">Net XP</div></div><div class="sb-stat"><div class="sb-stat-v {absent_cls}">{absent_count}</div><div class="sb-stat-l">Absent</div></div><div class="sb-stat"><div class="sb-stat-v b">{qc_done_today}</div><div class="sb-stat-l">QC Done</div></div></div>', unsafe_allow_html=True)
    team_xp_goal=1000; team_pct=min(100,int(team_xp/team_xp_goal*100))
    st.markdown(f'<div class="sb-xp"><div class="sb-xp-row"><span class="sb-xp-lbl">Target Tim</span><span class="sb-xp-val">{team_xp}/{team_xp_goal}</span></div><div class="sb-xp-track"><div class="sb-xp-fill" style="width:{team_pct}%"></div></div></div>', unsafe_allow_html=True)
    st.markdown("---")
    st.markdown('<div class="sb-lbl">Referensi Poin</div>', unsafe_allow_html=True)
    with st.expander("📊 Task & Penalti", expanded=False):
        rows="".join(f'<div class="pt-row"><span class="pt-n">{v[0]} {k}</span><span class="pt-p">+{v[2]}</span></div>' for k,v in TASK_TYPES.items())
        rows+="".join(f'<div class="pt-row"><span class="pt-n">{v[0]} {k}</span><span class="pt-p neg">{v[2]}</span></div>' for k,v in PENALTY_TYPES.items())
        rows+=('<div class="pt-row" style="border-top:1.5px solid var(--bd);margin-top:5px;padding-top:6px"><span class="pt-n" style="color:var(--g);font-weight:600">✅ Bonus Done</span><span class="pt-p">+5</span></div>'
               '<div class="pt-row"><span class="pt-n" style="color:var(--blu);font-weight:600">🔍 Bonus QC</span><span class="pt-p" style="color:var(--blu)">+10</span></div>')
        st.markdown(rows, unsafe_allow_html=True)
    with st.expander("🏅 Level XP", expanded=False):
        st.markdown("".join(f'<div class="pt-row"><span class="pt-n">{n}</span><span class="pt-p">{t}</span></div>' for t,n in LEVELS), unsafe_allow_html=True)
    st.markdown("---")
    if st.button("🔄  Refresh Data", use_container_width=True):
            update_activity()
            st.cache_data.clear()
            time.sleep(0.3)
            st.rerun()
    if st.button("🚪  Logout", use_container_width=True):
        try:
            nj_out=datetime.now(TZ_JKT); out_ts=nj_out.strftime("%Y-%m-%d %H:%M:%S")+" WIB"
            if st.session_state.login_time and st.session_state.session_row:
                dur=int((nj_out-st.session_state.login_time).total_seconds()/60)
                _,_,_ws3,_,_=get_sheets()
                if _ws3:
                    row=st.session_state.session_row
                    _ws3.update_cell(row,5,out_ts); _ws3.update_cell(row,6,dur); _ws3.update_cell(row,7,"Offline")
        except: pass
        st.session_state.update({"logged_in":False,"current_user":"","current_role":"","login_time":None,"session_row":None,"last_activity":None})
        st.query_params.clear(); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: INPUT TASK
# ══════════════════════════════════════════════════════════════════════════════
if "Input" in menu:
    if sheet_err: st.warning("⚠️ "+str(sheet_err))

    # ── Fire level up popup ───────────────────────────────────────────────────
    if st.session_state.get("level_up_pending"):
        lup = st.session_state.level_up_pending
        st.session_state.level_up_pending = None

        name_js  = lup["name"].replace("'", "\\'").replace('"', '\\"')
        color_js = lup["color"]
        xp_js    = lup["xp"]

        idx_map  = {"kitten":0,"kampung":1,"oyen":2,"garong":3,"elite":4,"sultan":5,"king":6}
        cat_js   = lup["cat"]
        idx      = idx_map.get(cat_js, 0)
        sub_msgs = [
            "Perjalananmu dimulai!",
            "Makin jago nih!",
            "Konsisten banget!",
            "Kamu keren banget!",
            "Level dewa!",
            "Sultan sejati!",
            "Raja Paw telah bangkit!",
        ]
        emojis   = ["🐱","😸","🐈","😼","🐆","👑","🏆"]
        next_xps = [100, 300, 600, 1000, 1800, 3000, 3000]

        sub_msg  = sub_msgs[idx]
        emoji    = emojis[idx]
        next_xp  = next_xps[idx]
        prog_pct = min(int(xp_js / next_xp * 100), 100) if next_xp > 0 else 100
        prog_lbl = "Max Level!" if xp_js >= 3000 else f"&#x2192; {next_xp} XP"

        # ── FIX 1: Tombol menggunakan addEventListener, bukan onclick inline ──
        st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@700;800;900&display=swap');
#lup-overlay{{
  position:fixed;inset:0;z-index:999999;
  background:rgba(18,15,26,0.50);
  backdrop-filter:blur(4px);
  -webkit-backdrop-filter:blur(4px);
  display:flex;align-items:center;justify-content:center;
  pointer-events:auto;
}}
#lup-canvas{{
  position:fixed;inset:0;
  pointer-events:none;
  z-index:999998;
}}
#lup-card{{
  background:#ffffff;
  border-radius:20px;
  padding:26px 30px 22px;
  width:272px;
  text-align:center;
  position:relative;
  overflow:hidden;
  z-index:1000000;
  box-shadow:0 20px 60px rgba(18,15,26,0.28);
  animation:lupPop .45s cubic-bezier(.34,1.56,.64,1) both;
  font-family:'Nunito',sans-serif;
  pointer-events:auto;
}}
@keyframes lupPop{{
  0%{{transform:scale(0.4);opacity:0}}
  75%{{transform:scale(1.05)}}
  100%{{transform:scale(1);opacity:1}}
}}
#lup-accent{{
  position:absolute;top:0;left:0;right:0;height:4px;
  background:{color_js};border-radius:20px 20px 0 0;
}}
@keyframes lupFloat{{
  0%,100%{{transform:translateY(0)}}
  50%{{transform:translateY(-7px)}}
}}
#lup-emoji{{
  font-size:58px;display:block;line-height:1.1;
  margin:4px auto 10px;
  animation:lupFloat 2s ease-in-out infinite;
}}
#lup-badge{{
  display:inline-block;
  font-size:10px;font-weight:800;
  padding:3px 13px;border-radius:99px;
  margin-bottom:9px;
  background:{color_js}22;
  color:{color_js};
  border:1.5px solid {color_js}66;
  font-family:'Nunito',sans-serif;
}}
#lup-title{{
  font-size:18px;font-weight:900;
  color:#120f1a;margin-bottom:3px;
  letter-spacing:-.3px;
  font-family:'Nunito',sans-serif;
}}
#lup-sub{{
  font-size:11px;color:#7a6e6a;
  margin-bottom:10px;font-weight:600;
  font-family:'Nunito',sans-serif;
}}
#lup-xp{{
  font-size:34px;font-weight:900;
  font-family:monospace;
  line-height:1;color:{color_js};display:block;
}}
#lup-xp-lbl{{
  font-size:9px;color:#b0a49e;
  text-transform:uppercase;letter-spacing:1px;
  margin-top:2px;margin-bottom:14px;display:block;
  font-family:'Nunito',sans-serif;
}}
#lup-prog-track{{
  background:#f0ece8;border-radius:99px;
  height:5px;overflow:hidden;margin-bottom:4px;
}}
#lup-prog-fill{{
  height:100%;border-radius:99px;
  background:{color_js};width:0;
  transition:width 1s ease-out;
}}
#lup-prog-labels{{
  display:flex;justify-content:space-between;
  font-size:9px;color:#b0a49e;font-weight:700;
  margin-bottom:16px;
  font-family:'Nunito',sans-serif;
}}
#lup-btn{{
  border:none;border-radius:12px;
  padding:12px 0;font-size:14px;font-weight:900;
  cursor:pointer;font-family:'Nunito',sans-serif;
  color:#fff;width:100%;
  background:{color_js};
  transition:all .15s;letter-spacing:.2px;
  pointer-events:auto;
  position:relative;
  z-index:1000001;
  display:block;
}}
#lup-btn:hover{{opacity:.88;transform:translateY(-1px);}}
#lup-btn:active{{transform:translateY(0);opacity:1;}}
</style>

<canvas id="lup-canvas"></canvas>
<div id="lup-overlay">
  <div id="lup-card">
    <div id="lup-accent"></div>
    <span id="lup-emoji">{emoji}</span>
    <div id="lup-badge">&#x1F389; Level Up!</div>
    <div id="lup-title">{name_js}</div>
    <div id="lup-sub">{sub_msg}</div>
    <span id="lup-xp">{xp_js}</span>
    <span id="lup-xp-lbl">XP Total</span>
    <div id="lup-prog-track">
      <div id="lup-prog-fill"></div>
    </div>
    <div id="lup-prog-labels">
      <span>{xp_js} XP</span>
      <span>{prog_lbl}</span>
    </div>
    <button id="lup-btn" type="button">Lanjut &#x2192;</button>
  </div>
</div>

<script>
(function(){{
  window._lupConfInt = null;

  function dismissLup() {{
    var ov = document.getElementById('lup-overlay');
    var cv = document.getElementById('lup-canvas');
    if(ov) {{ ov.style.transition = 'opacity .25s'; ov.style.opacity = '0'; }}
    if(window._lupConfInt) {{ clearInterval(window._lupConfInt); window._lupConfInt = null; }}
    if(cv) {{ cv.getContext('2d').clearRect(0, 0, cv.width, cv.height); }}
    setTimeout(function() {{
      if(ov) ov.style.display = 'none';
      if(cv) cv.style.display = 'none';
    }}, 260);
  }}

  function lupBurst(){{
    var cv = document.getElementById('lup-canvas');
    if(!cv) return;
    cv.width  = window.innerWidth;
    cv.height = window.innerHeight;
    var ctx = cv.getContext('2d');
    var cx  = cv.width / 2;
    var cy  = cv.height / 2;
    var cols   = ['{color_js}','#88bc77','#ccebf2','#f9e2b2','#f37973','#ffffff','#fbbf24','#a78bfa'];
    var shapes = ['circle','rect','star','diamond'];
    var pts = Array.from({{length:65}}, function(){{
      var a   = Math.random() * Math.PI * 2;
      var spd = Math.random() * 9 + 3;
      return {{
        x: cx, y: cy,
        vx: Math.cos(a) * spd,
        vy: Math.sin(a) * spd - 5,
        sz: Math.random() * 9 + 3,
        c:  cols[Math.floor(Math.random() * cols.length)],
        r:  Math.random() * 360,
        vr: (Math.random() - .5) * 12,
        life:  1,
        decay: Math.random() * 0.013 + 0.008,
        shape: shapes[Math.floor(Math.random() * shapes.length)]
      }};
    }});

    if(window._lupConfInt) clearInterval(window._lupConfInt);
    window._lupConfInt = setInterval(function(){{
      ctx.clearRect(0, 0, cv.width, cv.height);
      var alive = false;
      pts.forEach(function(p){{
        p.x += p.vx; p.y += p.vy; p.vy += 0.20;
        p.r += p.vr; p.life -= p.decay;
        if(p.life <= 0) return;
        alive = true;
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(p.r * Math.PI / 180);
        ctx.fillStyle   = p.c;
        ctx.globalAlpha = Math.max(0, p.life) * 0.92;
        var s = p.sz;
        if(p.shape === 'circle'){{
          ctx.beginPath(); ctx.arc(0,0,s/2,0,Math.PI*2); ctx.fill();
        }} else if(p.shape === 'rect'){{
          ctx.fillRect(-s/2,-s/4,s,s/2);
        }} else if(p.shape === 'diamond'){{
          ctx.beginPath();
          ctx.moveTo(0,-s/2); ctx.lineTo(s/2,0);
          ctx.lineTo(0,s/2);  ctx.lineTo(-s/2,0);
          ctx.closePath(); ctx.fill();
        }} else {{
          var n = 5;
          ctx.beginPath();
          for(var i = 0; i < n*2; i++){{
            var ang = i * Math.PI/n - Math.PI/2;
            var r2  = i%2===0 ? s/2 : s/4;
            if(i===0) ctx.moveTo(Math.cos(ang)*r2, Math.sin(ang)*r2);
            else      ctx.lineTo(Math.cos(ang)*r2, Math.sin(ang)*r2);
          }}
          ctx.closePath(); ctx.fill();
        }}
        ctx.restore();
      }});
      if(!alive){{
        clearInterval(window._lupConfInt);
        window._lupConfInt = null;
        ctx.clearRect(0, 0, cv.width, cv.height);
      }}
    }}, 16);
  }}

  var pf = document.getElementById('lup-prog-fill');
  if(pf) setTimeout(function(){{ pf.style.width = '{prog_pct}%'; }}, 120);
  lupBurst();

  // Bind tombol Lanjut via addEventListener (reliable di iframe Streamlit)
  setTimeout(function() {{
    var btn = document.getElementById('lup-btn');
    if(btn) {{
      btn.addEventListener('click', function(e) {{
        e.preventDefault();
        e.stopPropagation();
        dismissLup();
      }});
    }}
  }}, 50);
}})();
</script>
""", unsafe_allow_html=True)
    # ── End level up popup ────────────────────────────────────────────────────

    net_cls = "r" if net_today < 0 else "g"
    lv_idx  = next((i for i, (t, _) in enumerate(LEVELS) if t == level_min), 0)
    next_lv = LEVELS[min(lv_idx + 1, len(LEVELS) - 1)][1]

    st.markdown(
        f'<div class="staff-bar"><div class="sbar-l"><div class="sbar-av {role_cfg["av_class"]}">{initials}</div>'
        f'<div><div class="sbar-name">{sel}</div><div class="sbar-sub">Selamat {greeting} &nbsp;·&nbsp; {user_role} &nbsp;·&nbsp; {today_str}</div></div></div>'
        f'<div class="sbar-r"><div class="sbar-stat"><div class="sbar-stat-v g">+{xp_today}</div><div class="sbar-stat-l">XP Masuk</div></div>'
        f'<div class="sbar-div"></div><div class="sbar-stat"><div class="sbar-stat-v r">{pen_today}</div><div class="sbar-stat-l">Penalti</div></div>'
        f'<div class="sbar-div"></div><div class="sbar-stat"><div class="sbar-stat-v {net_cls}">{net_today}</div><div class="sbar-stat-l">Net XP</div></div>'
        f'<div class="sbar-div"></div><div class="sbar-lv">{level_name} &nbsp;·&nbsp; {xp_all} XP</div></div></div>',
        unsafe_allow_html=True)
    st.markdown(f'<div class="lvbar"><span class="lvbar-lbl">{level_name}</span><div class="lvbar-track"><div class="lvbar-fill" style="width:{level_pct}%"></div></div><span class="lvbar-pct">{level_pct}%</span><span class="lvbar-next">→ {next_lv} @ {level_max} XP</span></div>', unsafe_allow_html=True)
    st.markdown(missions_html(missions_booker(my_today)), unsafe_allow_html=True)

    if done_today > 0 and len(my_tasks) > 0 and done_today == len(my_tasks):
        st.markdown('<div style="background:linear-gradient(135deg,var(--g),var(--g2));border-radius:var(--r);padding:11px 18px;margin-bottom:14px;display:flex;align-items:center;gap:12px;box-shadow:var(--shg)"><span style="font-size:22px">🏆</span><div style="flex:1"><div style="font-size:12px;font-weight:700;color:#fff">Perfect Day! Semua task Done!</div><div style="font-size:10px;color:rgba(255,255,255,0.6)">Luar biasa, pertahankan terus!</div></div><div style="font-size:18px;font-weight:800;color:#fff;font-family:JetBrains Mono,monospace;background:rgba(255,255,255,0.15);border-radius:8px;padding:5px 13px">+100</div></div>', unsafe_allow_html=True)

    col_l, col_r = st.columns([3, 2], gap="medium")

    with col_l:
        st.markdown('<div class="sec-lbl">Tambah Aktivitas</div>', unsafe_allow_html=True)
        def fmt_option(x):
            entry = TASK_TYPES[x] if x in TASK_TYPES else PENALTY_TYPES[x]
            sign  = "+" if x in TASK_TYPES else ""
            return f"{entry[0]}  {x}  ({sign}{entry[2]} XP)"
        sel_item = st.selectbox("Jenis", ALL_OPTIONS, format_func=fmt_option, label_visibility="collapsed", key="item_sel")
        pen_mode = is_penalty(sel_item)
        if pen_mode:
            ico, kat, pts, dsc = PENALTY_TYPES[sel_item]
            bar_c, head_bg, head_bd = "var(--neg)", "var(--neglt)", "var(--negmd)"
            xp_c, xp_sign, default_status = "var(--neg)", "", "Penalti"
            ico_bg = "var(--neglt)"
        elif sel_item == "Booking Urgent":
            ico, kat, pts, dsc = TASK_TYPES[sel_item]
            bar_c, head_bg, head_bd = "var(--urg)", "var(--urglt)", "var(--urgmd)"
            xp_c, xp_sign, default_status = "var(--urg)", "+", "Done"
            ico_bg = "var(--urglt)"
        else:
            ico, kat, pts, dsc = TASK_TYPES[sel_item]
            bar_c, head_bg, head_bd = "var(--g)", "var(--gxlt)", "var(--gmd)"
            xp_c, xp_sign, default_status = "var(--g)", "+", "Done"
            ico_bg = "var(--glt)"
        st.markdown(f'<div class="ac-wrap"><div class="ac-head" style="background:{head_bg};border-color:{head_bd}"><div class="ac-bar" style="background:{bar_c}"></div><div class="ac-head-body"><div class="ac-left"><div class="ac-ico-wrap" style="background:{ico_bg}">{ico}</div><div><div class="ac-name">{sel_item}</div><div class="ac-sub">{dsc} · {kat}</div></div></div><span class="ac-xp" style="color:{xp_c}">{xp_sign}{pts+(DONE_BONUS if not pen_mode else 0)}</span></div></div>', unsafe_allow_html=True)

        with st.form("task_form", clear_on_submit=True):
            if not pen_mode:
                task_status  = st.selectbox("Status", STATUS_LIST, key="sts", label_visibility="collapsed")
                prev_xp      = pts + (DONE_BONUS if task_status == "Done" else 0)
                fc1, fc2     = st.columns(2)
                with fc1: checkin_date = st.date_input("📅 Check-in", value=None, min_value=date.today(), key="ci")
                with fc2: bid2 = st.text_input("🔖 Booking ID", placeholder="Opsional")
                fc3, fc4 = st.columns(2)
                with fc3: hotel = st.text_input("🏩 Nama Hotel", placeholder="Opsional")
                with fc4: notes = st.text_area("📝 Catatan", placeholder="Detail...", height=68)

                # ── Hitung hari diff & urgency ────────────────────────────────
                hari_diff = None
                is_urgent = False
                if checkin_date is not None:
                    hari_diff = (checkin_date - date.today()).days
                    is_urgent = hari_diff <= 1

                # ── FIX 2: Validasi Booking Urgent hanya H+0 / H+1 ───────────
                urgent_blocked = False

                if checkin_date is None:
                    st.markdown('<div class="strip neut">📅 Isi tanggal check-in untuk deteksi urgency</div>', unsafe_allow_html=True)
                    if sel_item == "Booking Urgent":
                        st.markdown('<div class="strip warn">⚠️ <b>Booking Urgent</b> wajib mengisi tanggal check-in (H+0 atau H+1).</div>', unsafe_allow_html=True)
                        urgent_blocked = True
                elif hari_diff < 0:
                    st.markdown('<div class="strip warn">⚠️ Tanggal check-in sudah lewat!</div>', unsafe_allow_html=True)
                    if sel_item == "Booking Urgent":
                        urgent_blocked = True
                elif is_urgent:
                    label = "hari ini" if hari_diff == 0 else "besok"
                    if sel_item == "Booking Urgent":
                        st.markdown(f'<div class="strip urg">⚡ Check-in {label}! Booking Urgent valid ✓</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div class="strip urg">⚡ Check-in {label}! Disarankan pilih <b>Booking Urgent (+25 XP)</b></div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="strip safe">✅ Check-in {hari_diff} hari lagi — Normal</div>', unsafe_allow_html=True)
                    if sel_item == "Booking Urgent":
                        st.markdown(f'<div class="strip warn">⚠️ <b>Booking Urgent hanya untuk check-in hari ini (H+0) atau besok (H+1).</b> Check-in masih {hari_diff} hari lagi — gunakan <b>Booking Hotel</b>.</div>', unsafe_allow_html=True)
                        urgent_blocked = True

                if not urgent_blocked and is_urgent and checkin_date is not None and sel_item != "Booking Urgent":
                    st.markdown(f'<div class="strip warn">⚠ Memilih <b>{sel_item}</b> padahal check-in mepet. Pastikan disengaja.</div>', unsafe_allow_html=True)

            else:
                task_status   = default_status
                prev_xp       = pts
                urgent_blocked = False  # Penalti tidak ada constraint urgency
                pc1, pc2      = st.columns(2)
                with pc1: bid2  = st.text_input("🔖 Booking ID", placeholder="Opsional")
                with pc2: notes = st.text_input("📝 Keterangan", placeholder="Ceritakan singkat...")
                hotel        = "-"
                checkin_date = None

            btn_label = (
                f"⚠️  Catat Penalti · {prev_xp} XP"  if pen_mode else
                f"⚡  Simpan Task · +{prev_xp} XP"    if sel_item == "Booking Urgent" else
                f"🐾  Simpan Task · +{prev_xp} XP"
            )
            form_submitted = st.form_submit_button(btn_label, use_container_width=True)

            if form_submitted:
                update_activity()
                # ── FIX 2: Blokir submit jika Booking Urgent tidak valid ──────
                if sel_item == "Booking Urgent" and urgent_blocked:
                    st.error("❌ Booking Urgent hanya berlaku untuk check-in hari ini (H+0) atau besok (H+1). Silakan pilih Booking Hotel untuk tanggal tersebut.")
                elif ws1 is None:
                    st.error("❌ Google Sheets tidak terhubung.")
                else:
                    nj = datetime.now(TZ_JKT)
                    ts = nj.strftime("%Y-%m-%d %H:%M:%S") + " WIB"
                    ci = str(checkin_date) if checkin_date else ""
                    if ci and not pen_mode:
                        full_notes = f"[Check-in: {ci}] {notes}".strip()
                    elif pen_mode and bid2:
                        full_notes = f"{notes} [Booking: {bid2}]"
                    else:
                        full_notes = notes
                    sla_min = ""
                    if not my_today.empty and "Timestamp" in my_today.columns:
                        try:
                            first_ts = my_today["Timestamp"].iloc[-1]
                            first_dt = datetime.strptime(first_ts[:19], "%Y-%m-%d %H:%M:%S")
                            sla_min  = str(int((nj.replace(tzinfo=None) - first_dt).total_seconds() / 60))
                        except:
                            pass
                    try:
                        ws1.append_row([str(date.today()), sel, user_role, kat, sel_item, bid2, hotel, full_notes, task_status, prev_xp, ts, "", sla_min, "Pending QC", "Pending QC", "", "0"])
                        st.cache_data.clear()
                        if not pen_mode:
                            old_level, _, _ = get_level(max(xp_all, 0))
                            new_xp_all      = xp_all + prev_xp
                            new_level, new_level_min, _ = get_level(max(new_xp_all, 0))
                            if new_level != old_level:
                                cat_type, cat_color = LEVEL_CAT_MAP.get(new_level, ("kitten", "#9ca3af"))
                                st.session_state.level_up_pending = {
                                    "name":  new_level,
                                    "xp":    new_level_min,
                                    "cat":   cat_type,
                                    "color": cat_color,
                                }
                        if pen_mode:
                            st.error(f"⬇️ Penalti {prev_xp} XP untuk **{sel}** ({sel_item}) dicatat.")
                        else:
                            st.success(f"✅ +{prev_xp} XP! **{sel_item}** tersimpan — {nj.strftime('%H:%M')} WIB")
                        st.rerun()
                    except Exception as exc:
                        st.error("❌ Gagal menyimpan: " + str(exc))

    with col_r:
        st.markdown('<div style="font-size:9px;font-weight:700;color:var(--mu);text-transform:uppercase;letter-spacing:1px;margin-bottom:10px">Timeline Hari Ini</div>', unsafe_allow_html=True)
        if my_today.empty:
            st.markdown('<div style="background:var(--wh);border:1px solid var(--bd);border-radius:var(--r);padding:36px;text-align:center;color:var(--fa);font-size:12px;box-shadow:var(--sh)">📭 Belum ada aktivitas hari ini</div>', unsafe_allow_html=True)
        else:
            sort_col = "Timestamp" if "Timestamp" in my_today.columns else my_today.columns[0]
            for idx, (_, row) in enumerate(my_today.sort_values(sort_col, ascending=False).iterrows()):
                tt    = row.get("Task Type", "")
                st_   = row.get("Status", "")
                ts_r  = row.get("Timestamp", "")
                ts_e  = str(row.get("Timestamp Edit", "")).strip()
                hr    = ts_r[11:16] if len(str(ts_r)) >= 16 else "--:--"
                hr_e  = ts_e[11:16] if len(ts_e) >= 16 else ""
                hotel_ = row.get("Hotel", "")
                bid   = row.get("Booking ID", "")
                nt    = row.get("Notes", "")
                xpr   = int(row.get("Poin", 0)) or calc_xp(tt, st_)
                pen   = is_penalty(tt)
                ico_t = PENALTY_TYPES.get(tt, TASK_TYPES.get(tt, ("📋", "", 0, "")))[0]
                meta  = " · ".join(str(x) for x in [hotel_, bid, nt] if x) or "-"
                bc    = ("sb-pen" if pen else (
                    "sb-done" if str(st_).lower() == "done" else
                    "sb-prog" if "progress" in str(st_).lower() else
                    "sb-pend" if any(w in str(st_).lower() for w in ["pending","waiting","hold"]) else
                    "sb-canc" if "cancel" in str(st_).lower() else "sb-oth"
                ))
                dot_cls = " neg" if pen else ""
                xp_cls  = " neg" if pen else ""
                xp_sign = "" if pen else "+"
                qc_f    = str(row.get("QC Finance", ""))
                sla_c, sla_t = sla_badge(row.get("SLA Minutes", ""))
                qc_html   = (f'<span class="{qc_badge(qc_f)}" style="font-size:9px">QC: {qc_f}</span>' if qc_f and qc_f not in ["", "0", "nan", "Pending QC"] else "")
                edit_html = (f'<span style="font-size:9px;color:var(--fa)">· Edit</span><span style="font-size:9px;font-weight:600;color:var(--urg);font-family:monospace">{hr_e}</span>' if hr_e else "")
                ts_html   = f'<div class="tl-time-row"><span style="font-size:9px;color:var(--fa)">Submit</span><span style="font-size:9px;font-weight:600;color:var(--mu);font-family:monospace">{hr}</span>{edit_html}<span class="{sla_c}">{sla_t}</span>{qc_html}</div>'
                st.markdown(
                    f'<div class="tl-card"><div class="tl-card-top">'
                    f'<div class="tl-dot{dot_cls}" style="margin-top:4px;flex-shrink:0"></div>'
                    f'<div class="tl-body"><div class="tl-nm">{ico_t} {tt}</div>'
                    f'<div class="tl-meta">{meta}</div>{ts_html}</div>'
                    f'<div class="tl-r"><div class="{bc}">{st_}</div>'
                    f'<div class="tl-xp{xp_cls}">{xp_sign}{xpr}</div></div></div>'
                    f'{"" if pen else "<div style=border-top:1px solid var(--bd2);margin-top:9px;padding-top:8px></div>"}',
                    unsafe_allow_html=True)
                if not pen and ws1 is not None:
                    ek = f"e_{idx}_{str(ts_r)[-6:]}"
                    ec1, ec2 = st.columns([3, 1])
                    with ec1:
                        ns = st.selectbox("s", STATUS_LIST, index=STATUS_LIST.index(st_) if st_ in STATUS_LIST else 0, key=ek, label_visibility="collapsed")
                    with ec2:
                        if st.button("✓", key="b" + ek, use_container_width=True):
                            if ns != st_:
                                update_activity()
                                try:
                                    nj2  = datetime.now(TZ_JKT)
                                    te   = nj2.strftime("%Y-%m-%d %H:%M:%S") + " WIB"
                                    cell = ws1.find(str(ts_r))
                                    if cell:
                                        ws1.update_cell(cell.row, 9,  ns)
                                        ws1.update_cell(cell.row, 10, calc_xp(tt, ns))
                                        ws1.update_cell(cell.row, 12, te)
                                        st.cache_data.clear()
                                        st.rerun()
                                except Exception as exc:
                                    st.error("❌ " + str(exc))

        if not my_today.empty:
            st.markdown(
                f'<div class="sum-row">'
                f'<div class="sum-item"><div class="sum-v">{len(my_tasks)}</div><div class="sum-l">Task</div></div>'
                f'<div class="sum-item"><div class="sum-v g">+{xp_today}</div><div class="sum-l">XP Masuk</div></div>'
                f'<div class="sum-item"><div class="sum-v r">{pen_today}</div><div class="sum-l">Penalti</div></div>'
                f'<div class="sum-item"><div class="sum-v {net_cls}">{net_today}</div><div class="sum-l">Net XP</div></div>'
                f'</div>',
                unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: QC SILANG
# ══════════════════════════════════════════════════════════════════════════════
if "QC Silang" in menu:
    update_activity()
    my_qc_total,my_qc_correct,my_qc_miss,my_qc_acc=get_qc_score(qc_score_df,sel)
    st.markdown(f'<div class="page-header" style="background:linear-gradient(135deg,#201b51,#4a9ab5)"><div class="ph-inner"><div class="ph-label">QC Silang · {today_str}</div><div class="ph-title">Blind QC · Quality Control</div><div class="ph-sub">{"QC Booker & Finance" if user_role=="Booker" else "QC Semua Transaksi Booker"} · Nama disembunyikan · Lock · Score</div></div><div class="ph-badge"><div class="ph-badge-v">{my_qc_acc}%</div><div class="ph-badge-l">Akurasi QC-ku</div></div></div>', unsafe_allow_html=True)
    acc_variant="green" if my_qc_acc>=90 else "yellow" if my_qc_acc>=70 else "red"
    st.markdown('<div class="kpi-row-4">'+kpi_card("🔍",len(my_qc_today),"QC Selesai Hari Ini","blue")+kpi_card("✅",my_qc_correct,"Temuan Akurat","green")+kpi_card("❌",my_qc_miss,"Miss (Terlewat)","red")+kpi_card("🎯",f"{my_qc_acc}%","Akurasi Score",acc_variant)+'</div>', unsafe_allow_html=True)
    st.markdown(missions_html(missions_finance(qc_df,sel),accent="var(--blu)"), unsafe_allow_html=True)
    if user_role=="Booker":
        st.markdown('<div class="strip safe">🤝 <b>Cross QC aktif</b> — Kamu bisa QC task Booker lain <b>dan</b> task Finance.</div>', unsafe_allow_html=True)
    st.markdown('<div class="strip info">🙈 <b>Blind QC aktif</b> — Nama staff yang input disembunyikan. Nilai berdasarkan fakta, bukan siapa yang input.</div>', unsafe_allow_html=True)
    if df.empty:
        st.info("📭 Belum ada transaksi.")
    else:
        if "Task Type" not in today_df.columns or today_df.empty:
            qc_pool=pd.DataFrame()
        else:
            base=today_df[(~today_df["Task Type"].isin(PENALTY_TYPES.keys()))&(today_df["Staff"]!=sel)]
            qc_pool=base[base["Role"].isin(["Booker","Finance"])] if "Role" in base.columns else base
        already_qc=set()
        if not qc_df.empty and "QC By" in qc_df.columns:
            already_qc=set(str(x) for x in qc_df[(qc_df["QC By"]==sel)&(qc_df["Date"]==today_str)]["Booking ID"].tolist())
        done_qc_ts=set()
        if not qc_df.empty and "Timestamp" in qc_df.columns:
            done_qc_ts=set(str(x) for x in qc_df[qc_df["Date"]==today_str]["Timestamp"].tolist())
        n_pending=len(qc_pool[~qc_pool["Timestamp"].astype(str).isin(done_qc_ts)]) if not qc_pool.empty else 0
        st.markdown(section_header("Antrian QC",f"{len(qc_pool)} transaksi · {n_pending} belum di-QC · {len(already_qc)} sudah kamu QC"), unsafe_allow_html=True)
        if qc_pool.empty:
            st.markdown('<div class="strip info">🔍 Belum ada transaksi yang perlu di-QC.</div>', unsafe_allow_html=True)
        else:
            sort_c="Timestamp" if "Timestamp" in qc_pool.columns else qc_pool.columns[0]
            for idx,(_,row) in enumerate(qc_pool.sort_values(sort_c,ascending=False).iterrows()):
                tt=row.get("Task Type",""); st2=row.get("Status",""); bid=str(row.get("Booking ID",""))
                hotel_=row.get("Hotel",""); nt=row.get("Notes",""); ts_r=row.get("Timestamp","")
                hr=ts_r[11:16] if len(str(ts_r))>=16 else "--:--"
                sla_c,sla_t=sla_badge(row.get("SLA Minutes",""))
                cur_qc_f=str(row.get("QC Finance","")); qc_b_val=str(row.get("QC Booker",""))
                lock_by=qc_b_val.replace("Locked:","").strip() if qc_b_val.startswith("Locked:") else None
                is_done_qc=bid in already_qc; is_locked_by_me=(lock_by==sel)
                is_locked_by_other=(lock_by is not None and lock_by!=sel)
                already_qcd_anyone=cur_qc_f not in ["","0","nan","Pending QC"]
                item_cls="ok" if (already_qcd_anyone or is_done_qc) else "needs-qc"
                blind_id=f"TRX-{str(abs(hash(ts_r)))[:5]}"
                task_ico=TASK_TYPES.get(tt,("📋","","",""))[0]; task_cat=TASK_TYPES.get(tt,("","","",""))[1] if tt in TASK_TYPES else "—"
                task_poin=row.get("Poin","—")
                checkin=""; notes_clean=nt or ""
                if "[Check-in:" in notes_clean:
                    try:
                        checkin=notes_clean.split("[Check-in:")[1].split("]")[0].strip()
                        notes_clean=notes_clean.split("]",1)[1].strip() if "]" in notes_clean else notes_clean
                    except: pass
                if is_done_qc or already_qcd_anyone: lock_badge='<span class="sb-qc-ok">✓ Selesai QC</span>'
                elif is_locked_by_me: lock_badge='<span style="font-size:9px;font-weight:700;padding:2px 9px;border-radius:99px;background:var(--urglt);color:var(--urg);border:1px solid var(--urgmd)">🔒 Kamu Lock</span>'
                elif is_locked_by_other: lock_badge=f'<span style="font-size:9px;font-weight:700;padding:2px 9px;border-radius:99px;background:var(--bllt);color:var(--blu);border:1px solid var(--blmd)">🔒 Dikerjakan orang lain</span>'
                else: lock_badge='<span class="sb-qc-pend">Belum di-QC</span>'
                notes_html=(f'<div style="font-size:10px;color:var(--mu);padding:7px 10px;background:#fafbff;border-radius:7px;border-left:3px solid var(--blmd);line-height:1.5;">📝 {notes_clean}</div>' if notes_clean else '<div style="font-size:10px;color:var(--fa);font-style:italic;">📝 Tidak ada catatan</div>')
                st.markdown(
                    f'<div class="qc-item {item_cls}" style="padding:14px 16px;">'
                    f'<div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px;">'
                    f'<div><div style="font-size:13px;font-weight:700;color:var(--tx);margin-bottom:3px;">{task_ico} {tt} &nbsp;<span style="font-size:10px;color:var(--mu);font-weight:500;font-family:monospace">{blind_id}</span></div>'
                    f'<div style="display:flex;gap:5px;flex-wrap:wrap;">{status_badge(st2)}<span class="{sla_c}">{sla_t}</span>'
                    f'<span style="font-size:9px;font-weight:700;padding:2px 8px;border-radius:99px;background:var(--bllt);color:var(--blu);border:1px solid var(--blmd)">{task_cat}</span>{lock_badge}</div></div>'
                    f'<div style="font-size:11px;font-weight:700;color:var(--g);font-family:JetBrains Mono,monospace;white-space:nowrap">+{task_poin} XP</div></div>'
                    f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;background:var(--bg);border-radius:8px;padding:10px 12px;margin-bottom:10px;">'
                    f'<div><div style="font-size:8px;font-weight:700;color:var(--fa);text-transform:uppercase;letter-spacing:.7px;margin-bottom:3px;">🏨 Hotel</div><div style="font-size:12px;font-weight:600;color:var(--tx)">{hotel_ or "—"}</div></div>'
                    f'<div><div style="font-size:8px;font-weight:700;color:var(--fa);text-transform:uppercase;letter-spacing:.7px;margin-bottom:3px;">📅 Check-in</div><div style="font-size:12px;font-weight:600;color:{"var(--neg)" if checkin else "var(--mu)"}">{checkin or "—"}</div></div>'
                    f'<div><div style="font-size:8px;font-weight:700;color:var(--fa);text-transform:uppercase;letter-spacing:.7px;margin-bottom:3px;">🔖 Booking ID</div><div style="font-size:12px;font-weight:600;color:var(--tx);font-family:monospace">{bid or "—"}</div></div></div>'
                    f'{notes_html}</div>', unsafe_allow_html=True)
                task_key=f"{ts_r}_{idx}"; is_my_active=(st.session_state.qc_locked_task==task_key)
                if not is_done_qc and not already_qcd_anyone:
                    if is_locked_by_other:
                        st.markdown('<div class="strip info" style="margin-top:4px;">🔒 Sedang di-QC orang lain. Tunggu atau pilih transaksi lain.</div>', unsafe_allow_html=True)
                    elif not is_my_active:
                        btn_col,_=st.columns([2,5])
                        with btn_col:
                            if st.button("🔒 Mulai QC", key=f"lock_{idx}_{str(ts_r)[-6:]}", use_container_width=True):
                                update_activity()
                                st.session_state.qc_locked_task=task_key
                                if ws1:
                                    try:
                                        cell=ws1.find(str(ts_r))
                                        if cell: ws1.update_cell(cell.row,15,f"Locked:{sel}")
                                        st.cache_data.clear()
                                    except: pass
                                st.rerun()
                if is_my_active and not is_done_qc and not already_qcd_anyone:
                    st.markdown(f'<div style="background:var(--gxlt);border:1px solid var(--gmd);border-radius:var(--r);padding:14px 16px;margin-top:8px;"><div style="font-size:11px;font-weight:700;color:var(--gdk);margin-bottom:10px;">🔍 Form QC · {blind_id}</div><div style="font-size:10px;background:var(--bllt);border:1px solid var(--blmd);border-radius:8px;padding:8px 12px;color:var(--blu);margin-bottom:10px;">🙈 <b>Blind QC</b> — Nama inputter disembunyikan. Nilai berdasarkan data transaksi.</div>', unsafe_allow_html=True)
                    qc1,qc2=st.columns(2)
                    with qc1: qc_result=st.selectbox("Hasil QC", QC_STATUS, key=f"qcr_{idx}_{str(ts_r)[-6:]}")
                    with qc2: qc_notes=st.text_input("Catatan QC", placeholder="Jelaskan temuanmu...", key=f"qcn_{idx}_{str(ts_r)[-6:]}")
                    col_submit,col_cancel=st.columns([3,1])
                    with col_submit:
                        if st.button(f"✅ Submit QC · {blind_id}", key=f"qcsub_{idx}_{str(ts_r)[-6:]}", use_container_width=True):
                            update_activity()
                            if ws1 is None or ws2 is None:
                                st.error("❌ Sheets tidak terhubung.")
                            else:
                                nj_qc=datetime.now(TZ_JKT); ts_qc=nj_qc.strftime("%Y-%m-%d %H:%M:%S")+" WIB"
                                found_issue=(qc_result=="Ada Isu"); xp_qc=QC_BONUS+(QC_FOUND_BONUS if found_issue else 0)
                                staff_b=row.get("Staff","")
                                try:
                                    cell_ts=ws1.find(str(ts_r))
                                    if cell_ts:
                                        rn=cell_ts.row; ws1.update_cell(rn,14,qc_result); ws1.update_cell(rn,15,qc_result); ws1.update_cell(rn,16,qc_notes); ws1.update_cell(rn,17,"1" if found_issue else "0")
                                    ws2.append_row([today_str,sel,user_role,staff_b,bid,tt,qc_result,qc_notes,xp_qc,ts_qc])
                                    ws1.append_row([today_str,sel,user_role,"QC","QC Silang",bid,"",f"QC: {tt} (blind)","Done",xp_qc,ts_qc,"","","","","","0"])
                                    update_qc_score(ws4,qc_score_df,sel,found_issue)
                                    st.session_state.qc_locked_task=None; st.cache_data.clear()
                                    st.success(f"✅ +{xp_qc} XP · {'🚨 Isu ditemukan' if found_issue else '✅ Transaksi bersih'} · Inputter: **{staff_b}**")
                                    st.rerun()
                                except Exception as exc: st.error(f"❌ {exc}")
                    with col_cancel:
                        if st.button("✕ Batal", key=f"cancel_{idx}_{str(ts_r)[-6:]}", use_container_width=True):
                            st.session_state.qc_locked_task=None
                            if ws1:
                                try:
                                    cell=ws1.find(str(ts_r))
                                    if cell: ws1.update_cell(cell.row,15,"Pending QC")
                                    st.cache_data.clear()
                                except: pass
                            st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown(section_header("🎯 QC Score — Akurasi Tim","Siapa QC-er paling teliti?"), unsafe_allow_html=True)
    if not qc_score_df.empty:
        score_sorted=qc_score_df.copy()
        score_sorted["Accuracy"]=pd.to_numeric(score_sorted["Accuracy"],errors="coerce").fillna(0)
        score_sorted["Total QC"]=pd.to_numeric(score_sorted["Total QC"],errors="coerce").fillna(0)
        score_sorted=score_sorted[score_sorted["Total QC"]>0].sort_values("Accuracy",ascending=False)
        mx_total=score_sorted["Total QC"].max() if len(score_sorted)>0 else 1
        for i,(_,r) in enumerate(score_sorted.iterrows()):
            sn=r["Staff"]; acc=int(r.get("Accuracy",0) or 0); tot=int(r.get("Total QC",0) or 0)
            cor=int(r.get("Correct",0) or 0); mis=int(r.get("Miss",0) or 0)
            bar_=int(tot/max(mx_total,1)*100); ini2=sn[:2].upper()
            acc_color="var(--g)" if acc>=90 else "var(--urg)" if acc>=70 else "var(--neg)"
            acc_cls="g" if acc>=90 else "y" if acc>=70 else "r"
            medal=rank_emoji(i+1) if i<3 else f"#{i+1}"
            st.markdown(f'<div class="lb {card_class(i+1)}"><div class="lb-rk {rank_class(i+1)}">{medal}</div><div class="lb-av" style="background:{acc_color}">{ini2}</div><div class="lb-info"><div class="lb-nm">{sn}</div><div class="lb-dt">{tot} QC · {cor} akurat · {mis} miss</div><div class="lb-bar"><div class="lb-fil" style="width:{bar_}%;background:{acc_color}"></div></div></div><div class="lb-rt"><div class="lb-pt sbar-stat-v {acc_cls}" style="color:{acc_color}">{acc}%</div><div style="font-size:9px;color:var(--mu)">Akurasi</div></div></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="strip neut">📊 Belum ada data QC Score. Mulai QC untuk melihat skor akurasi.</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: DASHBOARD SAYA
# ══════════════════════════════════════════════════════════════════════════════
if "Dashboard Saya" in menu:
    update_activity()
    st.markdown(f'<div class="page-header" style="background:linear-gradient(135deg,#201b51,#88bc77)"><div class="ph-inner"><div class="ph-label">Dashboard Saya · {today_str}</div><div class="ph-title">Performa: {sel}</div><div class="ph-sub">{user_role} · {level_name}</div></div><div class="ph-badge"><div class="ph-badge-v">{xp_all}</div><div class="ph-badge-l">Total XP</div></div></div>', unsafe_allow_html=True)
    error_count=(len(my_all[my_all["Error Flag"].astype(str)=="1"]) if not my_all.empty and "Error Flag" in my_all.columns else 0)
    done_all=(len(my_all[my_all["Status"]=="Done"]) if not my_all.empty and "Status" in my_all.columns else 0)
    done_pct=int(done_all/len(my_all)*100) if len(my_all)>0 else 0
    st.markdown('<div class="kpi-row-4">'+kpi_card("📋",len(my_all),"Total Task","gray")+kpi_card("⚡",xp_all,"Total XP","green")+kpi_card("✅",f"{done_pct}%","Done Rate","yellow" if done_pct<80 else "green")+kpi_card("🚨",error_count,"Error Ditemukan","red")+'</div>', unsafe_allow_html=True)
    c1,c2=st.columns(2)
    with c1:
        st.markdown(section_header("XP Harian — 7 Hari Terakhir"), unsafe_allow_html=True)
        if not my_all.empty and "Date" in my_all.columns and "Poin" in my_all.columns:
            daily=my_all.groupby("Date")["Poin"].sum().reset_index()
            daily["Date"]=pd.to_datetime(daily["Date"],errors="coerce")
            daily=daily.dropna().sort_values("Date").tail(7)
            fig=go.Figure(go.Bar(x=daily["Date"].dt.strftime("%d/%m"),y=daily["Poin"],marker=dict(color="#88bc77",line=dict(width=0)),text=daily["Poin"],textposition="outside",textfont=dict(color="#777",size=11)))
            fig.update_layout(**plotly_layout_base(200),xaxis=dict(showgrid=False,tickfont=dict(size=10,color="#111")),yaxis=dict(showgrid=True,gridcolor="#f0f0f0",showticklabels=False,zeroline=False),bargap=0.35)
            st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})
        else: st.info("Belum ada data.")
    with c2:
        st.markdown(section_header("Task per Jenis"), unsafe_allow_html=True)
        if not my_all.empty and "Task Type" in my_all.columns:
            my_ta=my_all[~my_all["Task Type"].isin(PENALTY_TYPES.keys())]
            if not my_ta.empty:
                tc=my_ta.groupby("Task Type").size().reset_index(name="n")
                fig2=go.Figure(go.Pie(labels=tc["Task Type"],values=tc["n"],hole=0.54,marker=dict(colors=CHART_GREENS,line=dict(color="#fff",width=2)),textinfo="percent",textfont=dict(size=10,color="white")))
                fig2.update_layout(**plotly_layout_base(200,margin={"l":0,"r":0,"t":4,"b":70}),legend=dict(font=dict(size=8,color="#777"),bgcolor="rgba(0,0,0,0)",orientation="h",x=0,y=-0.3),annotations=[dict(text=f"<b>{len(my_ta)}</b>",x=0.5,y=0.5,showarrow=False,font=dict(size=16,color="#111",family="JetBrains Mono"))])
                st.plotly_chart(fig2,use_container_width=True,config={"displayModeBar":False})
    st.markdown(section_header("Semua Task Saya"), unsafe_allow_html=True)
    if not my_all.empty:
        cols_show=["Date","Task Type","Status","Hotel","Booking ID","Poin","Timestamp"]
        if "QC Finance" in my_all.columns: cols_show.append("QC Finance")
        if "Error Flag" in my_all.columns: cols_show.append("Error Flag")
        st.dataframe(my_all[[c for c in cols_show if c in my_all.columns]].rename(columns={"Task Type":"Jenis","Booking ID":"Booking","Poin":"XP"}),use_container_width=True,height=280,hide_index=True)
    else: st.info("Belum ada task.")

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: MANAGER DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
if "Manager Dashboard" in menu:
    update_activity()
    st.markdown(f'<div class="page-header" style="background:linear-gradient(135deg,#120f1a,#201b51,#88bc77)"><div class="ph-inner"><div class="ph-label">Manager Dashboard · {today_str}</div><div class="ph-title">Performa Tim</div><div class="ph-sub">Real-time · XP masuk · QC · SLA · Error Rate</div></div></div>', unsafe_allow_html=True)
    absent_list=get_absent_staff(df,today_str)
    if absent_list:
        pills="".join(f'<span class="pill">{s}</span>' for s in absent_list)
        st.markdown(f'<div class="notif dn"><div class="ni">🔔</div><div class="nb"><div class="nt">{len(absent_list)} staff belum input hari ini</div><div class="nd">Segera ingatkan.</div><div class="pills">{pills}</div></div></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="notif ok"><div class="ni">🏆</div><div class="nb"><div class="nt">Semua staff sudah input hari ini!</div><div class="nd" style="margin-bottom:0">Tim komplet. Luar biasa!</div></div></div>', unsafe_allow_html=True)
    if df.empty: st.warning("⚠️ Belum ada data."); st.stop()
    fa,fb,fc,fd,_=st.columns([2,2,2,2,3])
    with fa: period=st.selectbox("Periode",["Hari Ini","7 Hari Terakhir","Semua"])
    with fb: f_staff=st.selectbox("Staff",["Semua"]+ALL_STAFF_FLAT)
    with fc: f_kat=st.selectbox("Kategori",["Semua","Reservasi","Payment","Penalti","QC"])
    with fd: f_role=st.selectbox("Role",["Semua","Booker","Finance","Manager"])
    fdf=df.copy()
    if "Date" in fdf.columns:
        fdf["Date"]=fdf["Date"].astype(str)
        if period=="Hari Ini": fdf=fdf[fdf["Date"]==today_str]
        elif period=="7 Hari Terakhir":
            fdf["_d"]=pd.to_datetime(fdf["Date"],errors="coerce")
            fdf=fdf[fdf["_d"]>=pd.Timestamp.now()-pd.Timedelta(days=7)].drop(columns="_d")
    if f_staff!="Semua" and "Staff" in fdf.columns: fdf=fdf[fdf["Staff"]==f_staff]
    if f_kat!="Semua" and "Kategori" in fdf.columns: fdf=fdf[fdf["Kategori"]==f_kat]
    if f_role!="Semua" and "Role" in fdf.columns: fdf=fdf[fdf["Role"]==f_role]
    fdf_task=fdf[~fdf["Task Type"].isin(PENALTY_TYPES.keys())] if "Task Type" in fdf.columns else fdf
    tot=len(fdf_task); dn=len(fdf_task[fdf_task["Status"]=="Done"]) if "Status" in fdf_task.columns else 0
    dnp=int(dn/tot*100) if tot>0 else 0; txp2=calc_xp_df(fdf_task)
    err_ct=len(fdf_task[fdf_task["Error Flag"].astype(str)=="1"]) if "Error Flag" in fdf_task.columns else 0
    err_pct=int(err_ct/tot*100) if tot>0 else 0; avg_sla="-"
    if "SLA Minutes" in fdf_task.columns:
        sv=pd.to_numeric(fdf_task["SLA Minutes"],errors="coerce").dropna()
        if len(sv)>0: avg_sla=str(int(sv.mean()))+"m"
    st.markdown('<div class="kpi-row">'+kpi_card("📋",tot,"Total Task","gray")+kpi_card("⚡",txp2,"Team XP","green")+kpi_card("✅",f"{dnp}%","Done Rate","yellow" if dnp<80 else "green")+kpi_card("⏱️",avg_sla,"Avg SLA","blue")+kpi_card("🚨",f"{err_pct}%","Error Rate","red")+'</div>', unsafe_allow_html=True)
    la,lb_col=st.columns([3,2])
    with la:
        st.markdown(section_header("Leaderboard Net XP"), unsafe_allow_html=True)
        if "Staff" in fdf.columns and not fdf.empty:
            lb_data=[]
            for sn in fdf["Staff"].unique():
                s_df=fdf[fdf["Staff"]==sn]
                s_t=s_df[~s_df["Task Type"].isin(PENALTY_TYPES.keys())] if "Task Type" in s_df.columns else s_df
                s_p=s_df[s_df["Task Type"].isin(PENALTY_TYPES.keys())] if "Task Type" in s_df.columns else pd.DataFrame()
                s_xp=calc_xp_df(s_t); s_pv=calc_penalty_df(s_p); s_net=s_xp+s_pv
                s_dn=len(s_t[s_t["Status"]=="Done"]) if "Status" in s_t.columns else 0
                s_pct=int(s_dn/len(s_t)*100) if len(s_t)>0 else 0
                s_err=len(s_t[s_t["Error Flag"].astype(str)=="1"]) if "Error Flag" in s_t.columns else 0
                s_role=str(s_df["Role"].iloc[0]) if "Role" in s_df.columns and len(s_df)>0 else "Booker"
                lvln2,_,_=get_level(max(s_net,0))
                lb_data.append({"s":sn,"xp":s_xp,"pen":s_pv,"net":s_net,"t":len(s_t),"pct":s_pct,"lvl":lvln2,"role":s_role,"err":s_err})
            lb_data.sort(key=lambda x:x["net"],reverse=True); mx=max(lb_data[0]["net"],1) if lb_data else 1
            for i,r in enumerate(lb_data):
                rk=i+1; bar_pct=int(max(r["net"],0)/max(mx,1)*100); ini2=r["s"][:2].upper()
                rc=ROLE_COLOR.get(r["role"],"var(--g)")
                pen_html=f'<div class="lb-neg">{r["pen"]} XP penalti</div>' if r["pen"]<0 else ""
                err_html=f'<div style="font-size:9px;color:var(--neg);font-weight:700">⚠ {r["err"]} error</div>' if r["err"]>0 else ""
                st.markdown(f'<div class="lb {card_class(rk)}"><div class="lb-rk {rank_class(rk)}">{rank_emoji(rk)}</div><div class="lb-av" style="background:{rc}">{ini2}</div><div class="lb-info"><div class="lb-nm">{r["s"]} <span style="font-size:9px;color:var(--mu)">({r["role"]})</span></div><div class="lb-dt">{r["t"]} task · {r["pct"]}% done</div><div class="lb-bar"><div class="lb-fil" style="width:{bar_pct}%"></div></div>{pen_html}{err_html}</div><div class="lb-rt"><div class="lb-pt" style="color:{rc}">{r["net"]}</div><div style="font-size:9px;color:var(--mu)">Net XP</div><div class="lb-lv">{r["lvl"]}</div></div></div>', unsafe_allow_html=True)
        else: st.info("Belum ada data.")
    with lb_col:
        st.markdown(section_header("Task per Jenis"), unsafe_allow_html=True)
        if "Task Type" in fdf_task.columns and not fdf_task.empty:
            tc=fdf_task.groupby("Task Type").size().reset_index(name="n")
            fig=go.Figure(go.Pie(labels=tc["Task Type"],values=tc["n"],hole=0.54,marker=dict(colors=CHART_GREENS,line=dict(color="#fff",width=2)),textinfo="percent",textfont=dict(size=10,color="white")))
            fig.update_layout(**plotly_layout_base(290,margin={"l":0,"r":0,"t":4,"b":80}),legend=dict(font=dict(size=9,color="#777"),bgcolor="rgba(0,0,0,0)",orientation="h",x=0,y=-0.3),annotations=[dict(text=f"<b>{len(fdf_task)}</b>",x=0.5,y=0.5,showarrow=False,font=dict(size=18,color="#111",family="JetBrains Mono"))])
            st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})
    c1,c2,c3=st.columns(3)
    with c1:
        st.markdown(section_header("XP per Staff"), unsafe_allow_html=True)
        if "Staff" in fdf.columns and not fdf.empty:
            xpd=[]
            for sn in fdf["Staff"].unique():
                s_df=fdf[fdf["Staff"]==sn]
                s_t=s_df[~s_df["Task Type"].isin(PENALTY_TYPES.keys())] if "Task Type" in s_df.columns else s_df
                s_p=s_df[s_df["Task Type"].isin(PENALTY_TYPES.keys())] if "Task Type" in s_df.columns else pd.DataFrame()
                xpd.append({"Staff":sn,"Net XP":calc_xp_df(s_t)+calc_penalty_df(s_p)})
            xpdf=pd.DataFrame(xpd).sort_values("Net XP")
            clrs=["#c0392b" if v<0 else "#88bc77" for v in xpdf["Net XP"]]
            fig2=go.Figure(go.Bar(x=xpdf["Net XP"],y=xpdf["Staff"],orientation="h",marker=dict(color=clrs,line=dict(width=0)),text=xpdf["Net XP"],textposition="outside",textfont=dict(color="#777",size=10)))
            fig2.update_layout(**plotly_layout_base(265,margin={"l":0,"r":42,"t":4,"b":0}),xaxis=dict(showgrid=True,gridcolor="#f0f0f0",zeroline=True,zerolinecolor="#ddd"),yaxis=dict(showgrid=False,tickfont=dict(size=10,color="#111")),bargap=0.38)
            st.plotly_chart(fig2,use_container_width=True,config={"displayModeBar":False})
    with c2:
        st.markdown(section_header("Reservasi vs Payment"), unsafe_allow_html=True)
        if "Kategori" in fdf_task.columns and not fdf_task.empty:
            kc=fdf_task[fdf_task["Kategori"].isin(["Reservasi","Payment"])].groupby("Kategori").size().reset_index(name="n")
            fig3=go.Figure(go.Bar(x=kc["Kategori"],y=kc["n"],marker=dict(color=["#88bc77","#5c8fa1"][:len(kc)],line=dict(width=0)),text=kc["n"],textposition="outside",textfont=dict(color="#777",size=13)))
            fig3.update_layout(**plotly_layout_base(240),xaxis=dict(showgrid=False,tickfont=dict(size=12,color="#111")),yaxis=dict(showgrid=True,gridcolor="#f0f0f0",showticklabels=False,zeroline=False),bargap=0.5)
            st.plotly_chart(fig3,use_container_width=True,config={"displayModeBar":False})
    with c3:
        st.markdown(section_header("Error Rate per Staff"), unsafe_allow_html=True)
        if "Error Flag" in fdf_task.columns and not fdf_task.empty and "Staff" in fdf_task.columns:
            ed=[{"Staff":sn,"Errors":len(fdf_task[(fdf_task["Staff"]==sn)&(fdf_task["Error Flag"].astype(str)=="1")])} for sn in fdf_task["Staff"].unique() if len(fdf_task[(fdf_task["Staff"]==sn)&(fdf_task["Error Flag"].astype(str)=="1")])>0]
            if ed:
                edf=pd.DataFrame(ed).sort_values("Errors")
                fig5=go.Figure(go.Bar(x=edf["Errors"],y=edf["Staff"],orientation="h",marker=dict(color="#d4736f",line=dict(width=0)),text=edf["Errors"],textposition="outside",textfont=dict(color="#777",size=11)))
                fig5.update_layout(**plotly_layout_base(240,margin={"l":0,"r":32,"t":4,"b":0}),xaxis=dict(showgrid=True,gridcolor="#f0f0f0",zeroline=False),yaxis=dict(showgrid=False,tickfont=dict(size=10,color="#111")),bargap=0.4)
                st.plotly_chart(fig5,use_container_width=True,config={"displayModeBar":False})
            else: st.markdown('<div style="text-align:center;padding:38px;color:var(--fa);font-size:12px">✅ Tidak ada error</div>', unsafe_allow_html=True)
    if "Date" in fdf.columns and fdf["Date"].nunique()>1:
        st.markdown(section_header("Tren XP Harian"), unsafe_allow_html=True)
        daily=(fdf.groupby("Date")["Poin"].sum().reset_index() if "Poin" in fdf.columns else fdf.groupby("Date").size().reset_index(name="Poin"))
        daily["Date"]=pd.to_datetime(daily["Date"],errors="coerce"); daily=daily.dropna().sort_values("Date")
        fig4=go.Figure(go.Scatter(x=daily["Date"],y=daily["Poin"],mode="lines+markers",line=dict(color="#88bc77",width=2.5),marker=dict(size=5,color="#88bc77",line=dict(color="white",width=2)),fill="tozeroy",fillcolor="rgba(60,174,80,0.07)",hovertemplate="<b>%{x|%d %b}</b><br>%{y} XP<extra></extra>"))
        fig4.update_layout(**plotly_layout_base(170),xaxis=dict(showgrid=False,tickfont=dict(size=10,color="#777")),yaxis=dict(showgrid=True,gridcolor="#f0f0f0",tickfont=dict(size=10,color="#777"),zeroline=True,zerolinecolor="#e0e0e0"))
        st.plotly_chart(fig4,use_container_width=True,config={"displayModeBar":False})
    st.markdown('<div class="div"></div>', unsafe_allow_html=True)
    st.markdown(section_header("Tabel Data Lengkap"), unsafe_allow_html=True)
    st.dataframe(fdf,use_container_width=True,height=300,hide_index=True)
    d1,_=st.columns([1,5])
    with d1:
        csv=fdf.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download CSV",csv,"task_report.csv",mime="text/csv")

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: QC MONITOR
# ══════════════════════════════════════════════════════════════════════════════
if "QC Monitor" in menu:
    update_activity()
    st.markdown(section_header("Monitor QC Hari Ini","Status QC silang per transaksi"), unsafe_allow_html=True)
    if today_df.empty:
        st.info("📭 Belum ada transaksi hari ini.")
    else:
        task_today=today_df[~today_df["Task Type"].isin(PENALTY_TYPES.keys())] if "Task Type" in today_df.columns else today_df
        needs_qc=(task_today[task_today["QC Finance"].astype(str).isin(["","Pending QC","nan","0"])] if "QC Finance" in task_today.columns else task_today)
        has_issue=(task_today[task_today["Error Flag"].astype(str)=="1"] if "Error Flag" in task_today.columns else pd.DataFrame())
        st.markdown('<div class="kpi-row-3">'+kpi_card("🔍",len(task_today),"Total Transaksi","gray")+kpi_card("⏳",len(needs_qc),"Perlu QC","yellow")+kpi_card("🚨",len(has_issue),"Ada Isu","red")+'</div>', unsafe_allow_html=True)
        sort_c="Timestamp" if "Timestamp" in task_today.columns else task_today.columns[0]
        for _,row in task_today.sort_values(sort_c,ascending=False).iterrows():
            tt=row.get("Task Type",""); st2=row.get("Status",""); bid=str(row.get("Booking ID",""))
            staff_b=row.get("Staff",""); hotel_=row.get("Hotel",""); ts_r=row.get("Timestamp","")
            hr=ts_r[11:16] if len(str(ts_r))>=16 else "--:--"
            qc_f=str(row.get("QC Finance","")); err=str(row.get("Error Flag","0"))
            sla_c,sla_t=sla_badge(row.get("SLA Minutes",""))
            item_cls="has-issue" if err=="1" else ("ok" if "ok" in qc_f.lower() else "needs-qc")
            qc_display=qc_f if qc_f not in ["","nan","0","Pending QC"] else "Pending"
            err_html = "<span class='sla-over'>&#9888; Error</span>" if err == "1" else ""
            st.markdown(f'<div class="qc-item {item_cls}"><div class="qc-top"><div><div class="qc-id">{TASK_TYPES.get(tt,("📋","","",""))[0]} {tt}&nbsp;<span style="font-size:10px;color:var(--mu)">#{bid or "-"} &middot; {staff_b}</span></div><div class="qc-meta">{hotel_} &middot; {hr}</div></div><div class="qc-badges"><span class="{status_badge(st2)}">{st2}</span><span class="{sla_c}">{sla_t}</span><span class="{qc_badge(qc_f)}">QC-F: {qc_display}</span>{err_html}</div></div></div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: LEADERBOARD
# ══════════════════════════════════════════════════════════════════════════════
if "Leaderboard" in menu:
    update_activity()
    st.markdown(section_header("Leaderboard Tim","Ranking berdasarkan Net XP"), unsafe_allow_html=True)
    if df.empty: st.info("Belum ada data.")
    else:
        fa2,fb2=st.columns([2,2])
        with fa2: period_lb=st.selectbox("Periode LB",["Hari Ini","7 Hari Terakhir","Semua"],key="lb_sd")
        with fb2: role_lb=st.selectbox("Role LB",["Semua","Booker","Finance"],key="lb_sr")
        fdf2=df.copy()
        if "Date" in fdf2.columns:
            fdf2["Date"]=fdf2["Date"].astype(str)
            if period_lb=="Hari Ini": fdf2=fdf2[fdf2["Date"]==today_str]
            elif period_lb=="7 Hari Terakhir":
                fdf2["_d"]=pd.to_datetime(fdf2["Date"],errors="coerce")
                fdf2=fdf2[fdf2["_d"]>=pd.Timestamp.now()-pd.Timedelta(days=7)].drop(columns="_d")
        if role_lb!="Semua" and "Role" in fdf2.columns: fdf2=fdf2[fdf2["Role"]==role_lb]
        lb2=[]
        for sn in fdf2["Staff"].unique():
            if sn=="Manager": continue
            s_df=fdf2[fdf2["Staff"]==sn]
            s_t=s_df[~s_df["Task Type"].isin(PENALTY_TYPES.keys())] if "Task Type" in s_df.columns else s_df
            s_p=s_df[s_df["Task Type"].isin(PENALTY_TYPES.keys())] if "Task Type" in s_df.columns else pd.DataFrame()
            s_xp=calc_xp_df(s_t); s_pv=calc_penalty_df(s_p); s_net=s_xp+s_pv
            s_dn=len(s_t[s_t["Status"]=="Done"]) if "Status" in s_t.columns else 0
            s_pct=int(s_dn/len(s_t)*100) if len(s_t)>0 else 0
            s_err=len(s_t[s_t["Error Flag"].astype(str)=="1"]) if "Error Flag" in s_t.columns else 0
            s_role=str(s_df["Role"].iloc[0]) if "Role" in s_df.columns and len(s_df)>0 else "Booker"
            lvln2,_,_=get_level(max(s_net,0))
            streak=0
            if "Date" in s_df.columns:
                dates=sorted(s_df["Date"].unique(),reverse=True)
                for i,d in enumerate(dates):
                    try:
                        if datetime.strptime(str(d),"%Y-%m-%d").date()==date.today()-timedelta(days=i): streak+=1
                        else: break
                    except: break
            lb2.append({"s":sn,"xp":s_xp,"pen":s_pv,"net":s_net,"t":len(s_t),"pct":s_pct,"lvl":lvln2,"role":s_role,"err":s_err,"streak":streak})
        lb2.sort(key=lambda x:x["net"],reverse=True); mx2=max(lb2[0]["net"],1) if lb2 else 1
        for i,r in enumerate(lb2):
            rk=i+1; bar_pct=int(max(r["net"],0)/max(mx2,1)*100); ini2=r["s"][:2].upper()
            rc={"Finance":"var(--blu)","Booker":"var(--g)"}.get(r["role"],"var(--g)")
            pen_html=f'<span class="lb-neg">{r["pen"]} XP &nbsp;</span>' if r["pen"]<0 else ""
            err_html=f'<span style="font-size:9px;color:var(--neg);font-weight:700">⚠ {r["err"]} error &nbsp;</span>' if r["err"]>0 else ""
            str_html=f'<span style="font-size:9px;color:var(--urg);font-weight:700">🔥 {r["streak"]} hari</span>' if r["streak"]>0 else ""
            st.markdown(f'<div class="lb {card_class(rk)}"><div class="lb-rk {rank_class(rk)}">{rank_emoji(rk)}</div><div class="lb-av" style="background:{rc}">{ini2}</div><div class="lb-info"><div class="lb-nm">{r["s"]} <span style="font-size:9px;color:var(--mu)">({r["role"]})</span></div><div class="lb-dt">{r["t"]} task · {r["pct"]}% done</div><div class="lb-bar"><div class="lb-fil" style="width:{bar_pct}%"></div></div><div style="margin-top:3px">{pen_html}{err_html}{str_html}</div></div><div class="lb-rt"><div class="lb-pt" style="color:{rc}">{r["net"]}</div><div style="font-size:9px;color:var(--mu)">Net XP</div><div class="lb-lv">{r["lvl"]}</div></div></div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: SESSION MONITOR
# ══════════════════════════════════════════════════════════════════════════════
if "Session Monitor" in menu and user_role=="Manager":
    update_activity()
    st.markdown(f'<div class="page-header" style="background:linear-gradient(135deg,#201b51,#88bc77,#ccebf2)"><div class="ph-inner"><div class="ph-label">Session Monitor · {today_str}</div><div class="ph-title">Durasi Login Staff</div><div class="ph-sub">Rekap waktu login & aktivitas hari ini</div></div></div>', unsafe_allow_html=True)
    now_jkt=datetime.now(TZ_JKT); live_sessions={}; all_sessions_today=[]
    if not session_df.empty:
        for _,row in session_df.iterrows():
            if str(row.get("Date",""))==today_str:
                all_sessions_today.append(row.to_dict())
                if str(row.get("Status",""))=="Online": live_sessions[row.get("Staff","")]=row.to_dict()
    total_online=len(live_sessions); total_today=len(set(r.get("Staff","") for r in all_sessions_today))
    staff_no_mgr=ALL_STAFF["Finance"]+ALL_STAFF["Booker"]
    total_offline=len([s for s in staff_no_mgr if s not in live_sessions])
    st.markdown('<div class="kpi-row-3">'+kpi_card("🟢",total_online,"Sedang Online","green")+kpi_card("👤",total_today,"Login Hari Ini","blue")+kpi_card("⭕",total_offline,"Belum Login","yellow" if total_offline>0 else "green")+'</div>', unsafe_allow_html=True)
    st.markdown(section_header("🟢 Sedang Online Sekarang",f"{total_online} staff aktif"), unsafe_allow_html=True)
    if not live_sessions:
        st.markdown('<div class="strip neut">⭕ Tidak ada staff yang sedang online saat ini.</div>', unsafe_allow_html=True)
    else:
        for staff_name,row in sorted(live_sessions.items()):
            login_dt=parse_jkt(row.get("Login Time",""))
            if login_dt: dur_mins=int((now_jkt-login_dt).total_seconds()/60); dur_str=format_duration(dur_mins); login_hm=login_dt.strftime("%H:%M")
            else: dur_str="-"; login_hm=str(row.get("Login Time",""))[:5]
            role_s=row.get("Role",""); ini_s=staff_name[:2].upper(); rc_color=ROLE_COLOR.get(role_s,"var(--g)"); rc_cls=ROLE_CLASS.get(role_s,"booker")
            task_ct=len(df[(df["Staff"]==staff_name)&(df["Date"]==today_str)]) if not df.empty and "Staff" in df.columns else 0
            st.markdown(f'<div class="staff-bar" style="margin-bottom:8px;"><div class="sbar-l"><div class="sbar-av {rc_cls}" style="background:{rc_color}">{ini_s}</div><div><div class="sbar-name">{staff_name}</div><div class="sbar-sub">{role_s} &nbsp;·&nbsp; Login {login_hm} WIB</div></div></div><div class="sbar-r"><div class="sbar-stat"><div class="sbar-stat-v g">{dur_str}</div><div class="sbar-stat-l">Durasi</div></div><div class="sbar-div"></div><div class="sbar-stat"><div class="sbar-stat-v">{task_ct}</div><div class="sbar-stat-l">Task Hari Ini</div></div><div class="sbar-div"></div><div style="background:var(--glt);border:1px solid var(--gmd);border-radius:var(--rpill);padding:5px 12px;font-size:10px;font-weight:700;color:var(--g);">🟢 Online</div></div></div>', unsafe_allow_html=True)
    st.markdown(section_header("📋 Riwayat Sesi Hari Ini",f"{len(all_sessions_today)} sesi tercatat"), unsafe_allow_html=True)
    if not all_sessions_today:
        st.markdown('<div class="strip neut">📭 Belum ada riwayat sesi hari ini.</div>', unsafe_allow_html=True)
    else:
        for row in sorted(all_sessions_today,key=lambda r:str(r.get("Login Time","")),reverse=True):
            staff_name=row.get("Staff",""); role_s=row.get("Role","")
            login_ts=str(row.get("Login Time","")); logout_ts=str(row.get("Logout Time",""))
            dur_raw=row.get("Duration Minutes",""); status=row.get("Status","")
            login_hm=login_ts[11:16] if len(login_ts)>=16 else login_ts[:5]
            logout_hm=logout_ts[11:16] if len(logout_ts)>=16 else ("-" if not logout_ts else logout_ts[:5])
            ini_s=staff_name[:2].upper(); rc_color=ROLE_COLOR.get(role_s,"var(--g)")
            if status=="Online":
                login_dt=parse_jkt(login_ts)
                dur_disp=format_duration(int((now_jkt-login_dt).total_seconds()/60)) if login_dt else "-"
                status_badge_html='<span style="font-size:9px;font-weight:700;padding:2px 8px;border-radius:99px;background:var(--glt);color:var(--gdk);border:1px solid var(--gmd)">🟢 Online</span>'
            else:
                try: dur_disp=format_duration(int(float(dur_raw)))
                except: dur_disp="-"
                status_badge_html='<span style="font-size:9px;font-weight:700;padding:2px 8px;border-radius:99px;background:var(--bg);color:var(--mu);border:1px solid var(--bd)">⭕ Offline</span>'
            st.markdown(f'<div class="tl-card"><div class="tl-card-top"><div style="width:28px;height:28px;border-radius:8px;background:{rc_color};display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:#fff;flex-shrink:0;">{ini_s}</div><div class="tl-body"><div class="tl-nm">{staff_name} <span style="font-size:9px;color:var(--mu);font-weight:400">({role_s})</span></div><div class="tl-time-row" style="margin-top:4px"><span style="font-size:9px;color:var(--fa)">Login</span><span style="font-size:9px;font-weight:600;color:var(--mu);font-family:monospace">{login_hm}</span><span style="font-size:9px;color:var(--fa)">· Logout</span><span style="font-size:9px;font-weight:600;color:var(--mu);font-family:monospace">{logout_hm}</span></div></div><div class="tl-r">{status_badge_html}<div style="font-size:11px;font-weight:700;color:var(--blu);font-family:JetBrains Mono,monospace;margin-top:4px;">⏱ {dur_disp}</div></div></div></div>', unsafe_allow_html=True)
    st.markdown(section_header("📊 Ringkasan Durasi — 7 Hari Terakhir"), unsafe_allow_html=True)
    if not session_df.empty:
        try:
            sess_df=session_df.copy(); sess_df["Date"]=pd.to_datetime(sess_df["Date"],errors="coerce")
            cutoff=pd.Timestamp.now()-pd.Timedelta(days=7); sess_week=sess_df[sess_df["Date"]>=cutoff].copy()
            if not sess_week.empty and "Duration Minutes" in sess_week.columns:
                sess_week["Duration Minutes"]=pd.to_numeric(sess_week["Duration Minutes"],errors="coerce").fillna(0)
                summary=sess_week.groupby(["Staff","Role"])["Duration Minutes"].sum().reset_index()
                summary["Jam"]=(summary["Duration Minutes"]//60).astype(int)
                summary["Menit"]=(summary["Duration Minutes"]%60).astype(int)
                summary["Durasi"]=summary.apply(lambda r:f"{r['Jam']}j {r['Menit']}m" if r["Jam"]>0 else f"{r['Menit']}m",axis=1)
                summary["Sessions"]=sess_week.groupby("Staff").size().reindex(summary["Staff"]).values
                summary=summary.sort_values("Duration Minutes",ascending=False); max_dur=summary["Duration Minutes"].max()
                for _,row in summary.iterrows():
                    sn=row["Staff"]; rl=row["Role"]; rc_color=ROLE_COLOR.get(rl,"var(--g)")
                    bar_pct=int(row["Duration Minutes"]/max(max_dur,1)*100); ini_s=sn[:2].upper()
                    st.markdown(f'<div class="lb"><div class="lb-av" style="background:{rc_color}">{ini_s}</div><div class="lb-info"><div class="lb-nm">{sn} <span style="font-size:9px;color:var(--mu)">({rl})</span></div><div class="lb-dt">{int(row["Sessions"])} sesi dalam 7 hari</div><div class="lb-bar"><div class="lb-fil" style="width:{bar_pct}%;background:linear-gradient(90deg,var(--blu),#4a9cf0)"></div></div></div><div class="lb-rt"><div class="lb-pt" style="color:var(--blu)">{row["Durasi"]}</div><div style="font-size:9px;color:var(--mu)">Total Login</div></div></div>', unsafe_allow_html=True)
        except: st.info("Belum ada data sesi minggu ini.")
