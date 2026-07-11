//go:build windows

package main

import (
    "fmt"
    "os"
    "os/exec"
    "path/filepath"
    "syscall"
)

const (
    createNewConsole = 0x00000010
    createNoWindow   = 0x08000000
)

func projectDir() (string, error) {
    exe, err := os.Executable()
    if err != nil {
        return "", err
    }
    exe, err = filepath.Abs(exe)
    if err != nil {
        return "", err
    }
    return filepath.Dir(exe), nil
}

func verifyEnvironment(dir string) bool {
    py := filepath.Join(dir, ".venv", "Scripts", "python.exe")
    if _, err := os.Stat(py); err != nil {
        return false
    }
    check := exec.Command(py, "-c", "import PySide6,serial,openpyxl,numpy,scipy,sounddevice,webrtcvad,sklearn,pandas; import faster_whisper")
    check.Dir = dir
    check.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow}
    return check.Run() == nil
}

func runInstaller(dir string) error {
    installer := filepath.Join(dir, "install_hangul_tactile_designer.bat")
    cmd := exec.Command("cmd.exe", "/d", "/c", "call", installer, "/nopause")
    cmd.Dir = dir
    cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: createNewConsole}
    return cmd.Run()
}

func launchApp(dir string) error {
    pyw := filepath.Join(dir, ".venv", "Scripts", "pythonw.exe")
    if _, err := os.Stat(pyw); err != nil {
        pyw = filepath.Join(dir, ".venv", "Scripts", "python.exe")
    }
    launcher := filepath.Join(dir, "launch_hangul_tactile_designer.py")
    cmd := exec.Command(pyw, launcher)
    cmd.Dir = dir
    cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow}
    return cmd.Start()
}

func showFailure(dir string, reason error) {
    message := fmt.Sprintf("Hangul Tactile Designer could not start.\r\n\r\n%s\r\n\r\nRun diagnose_environment.bat in:\r\n%s", reason, dir)
    ps := exec.Command("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show($args[0], 'Hangul Tactile Designer', 'OK', 'Error') | Out-Null", message)
    ps.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow}
    _ = ps.Run()
}

func main() {
    dir, err := projectDir()
    if err != nil {
        return
    }

    if !verifyEnvironment(dir) {
        if err := runInstaller(dir); err != nil {
            showFailure(dir, fmt.Errorf("installation failed: %w", err))
            return
        }
    }

    if !verifyEnvironment(dir) {
        showFailure(dir, fmt.Errorf("the Python environment is still incomplete after installation"))
        return
    }

    if err := launchApp(dir); err != nil {
        showFailure(dir, fmt.Errorf("launch failed: %w", err))
    }
}
