# BilimBagdar v3 — Google Sheets (тұрақты сақтау)

## Не сақталады?
- Үй тапсырмалар: Sheet `homework`
- Оқушы жұмыстары: Sheet `submissions`
- Логиндер: Sheet `users`

## 1) Google Sheet жасау
Google Drive → New → Google Sheets (мыс: `BilimBagdarDB`)  
URL-дан Sheet ID алыңыз: `/d/<ID>/edit`

## 2) Google Cloud-та Service Account
- Google Cloud Console → Project
- APIs қосыңыз:
  - Google Sheets API
  - Google Drive API (файлдар керек болса)
- Service Account жасаңыз → JSON key жүктеңіз

## 3) Рұқсат беру
- Sheet-ті service account email-ына Share жасаңыз (Editor)
- Файл жүктеу үшін:
  - Drive-та папка жасаңыз, соны да service account email-ына Share жасаңыз
  - папканың Folder ID-ін алыңыз

## 4) Streamlit Secrets
Streamlit Cloud → App → Settings → Secrets:
```txt
GCP_SERVICE_ACCOUNT='{"type":"service_account", ... }'
GSHEET_ID="сіздің_sheet_id"
DRIVE_FOLDER_ID="сіздің_drive_folder_id"   # optional (ұсынылады)
OPENAI_API_KEY="..."                       # optional
```

## 5) Іске қосу
```bash
pip install -r requirements.txt
streamlit run app.py
```

> DRIVE_FOLDER_ID қоспасаңыз, файлдар base64 ретінде сақталуы мүмкін (үлкен файлға ұсынылмайды).


## GitHub-қа жүктеу (толық нұсқа)
1) GitHub → **New repository** → атауы: `BilimBagdar`
2) Репозиторий ашылған соң → **Add file → Upload files**
3) Осы архивтен мына 3 файлды жүктеңіз:
   - `app.py`
   - `requirements.txt`
   - `README.md`
4) **Commit changes**

## Streamlit Community Cloud-та жариялау
1) Streamlit Community Cloud → **New app**
2) GitHub репосын таңдаңыз: `BilimBagdar`
3) Main file path: `app.py`
4) **Deploy**
5) Қосымша ашылған соң: App → **Settings → Secrets** бөліміне Google Sheets/Drive кілттерін енгізіңіз (төмендегі бөлім).

## Пайдаланушылар (ұсыныс)
Алғашқыда 1 мұғалім аккаунтын Sheets бетіне қолмен қосып қоюға болады:
- Sheet: `users`
- role: `teacher`
- username: `teacher`
- password_hash: (SHA256 қажет)

Ең ыңғайлысы: мен келесі қадамда «әкімші арқылы мұғалім аккаунтын бірінші рет құру» (bootstrap) функциясын қосып берем.


## Алғашқы мұғалімді тіркеу (bootstrap)
Егер `users` бетінде мұғалім болмаса, қосымша автоматты түрде **«Алғашқы мұғалімді тіркеу»** экранын ашады.
Сол жерде аты-жөніңіз, логин, пароль енгізесіз — жүйе өзі сақтап, бірден кіргізеді.
