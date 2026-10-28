# SDU Portal — фронт, подключённый к API

Запуск (два окна PowerShell):

1) Бэкенд: `cd C:\Users\ilash\SSPMS` → `.\.venv\Scripts\Activate.ps1` → `python -m backend.app`
2) Фронт: `cd C:\Users\ilash\SSPMS\frontend` → `npm install` → `npm run dev` → http://localhost:5173

Входы: студент 2400003 / demo1234, преподаватель T001 / demo1234.
Демо без бэкенда: в `.env` поставить `VITE_DEMO_MODE=true`.
