@echo off
setlocal
if exist "%~dp0venv\Scripts\flask.exe" (
    "%~dp0venv\Scripts\python.exe" %*
) else if exist "C:\Users\Shilpa\Desktop\medi_voice_to_pres\updated_medivoice_to_prescription\MedScript_AI_appointment_booking_update\medical_audio_prescription_system\venv\Scripts\python.exe" (
    "C:\Users\Shilpa\Desktop\medi_voice_to_pres\updated_medivoice_to_prescription\MedScript_AI_appointment_booking_update\medical_audio_prescription_system\venv\Scripts\python.exe" %*
) else (
    py -3.12 %*
)
