@echo off
rem ��ƵתͼƬ���� - ˫������
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo δ�ҵ����⻷�� .venv�����Ȱ�װ����
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "��ƵתͼƬ.py"
exit
