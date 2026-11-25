# Dedicated WorkTrack kiosk laptop

1. Create a separate, standard Windows account for the shared attendance laptop. Do not use the Administrator's everyday Windows account.
2. Sign in to that Windows account and start the WorkTrack application (or connect the SSH tunnel if WorkTrack is hosted on EC2).
3. Run `Start-WorkTrackKiosk.ps1` from PowerShell. The script starts Chrome with a dedicated persistent profile in kiosk display mode and opens the WorkTrack activation page.
4. On first use, sign in to WorkTrack with a dedicated WorkTrack Administrator account, open the QR kiosk activation page, and confirm that Administrator's password. Do not leave the Admin dashboard signed in on a public/shared profile.
5. Keep the Windows account restricted to the kiosk workflow. For stronger OS-level lockdown, configure Windows Assigned Access / a Windows kiosk account to launch Chrome. Chrome's `--kiosk` display flag alone is not a security boundary and does not disable all Windows keyboard shortcuts.
6. To leave the WorkTrack kiosk page, use **Administrator exit** and re-enter the same Administrator account's password.

The WorkTrack server enforces the application-level session lock. The Windows setup is a separate additional layer to prevent access to other desktop applications and browser controls.

The browser profile is persistent so its authenticated session can be reused. Keep the laptop physically secured and do not share the Windows profile with ordinary staff.
