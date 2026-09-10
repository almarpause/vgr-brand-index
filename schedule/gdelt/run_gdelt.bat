@echo off
cd /d "C:\Users\aresi\Claude\code\brand-index"
"C:\Users\aresi\AppData\Local\Programs\Python\Python313\python.exe" "C:\Users\aresi\Claude\code\brand-index\schedule\gdelt\gdelt_loop.py" >> "C:\Users\aresi\Claude\code\brand-index\refresh_500\gdelt_scheduled_run.log" 2>&1
