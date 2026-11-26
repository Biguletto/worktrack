# WorkTrack QR Kiosk Operator Guide

## Start the kiosk

1. Sign in to WorkTrack with the dedicated Administrator account assigned to the kiosk laptop.
2. Open **Activate QR Kiosk** from the Administrator dashboard.
3. Confirm the Administrator username and password.
4. WorkTrack opens the standalone scanner and requests camera access. The camera starts automatically after page load.
5. Allow the camera permission prompt. Keep the browser at localhost or HTTPS.

The kiosk page shows only the camera, brief instructions, and today's attendance log. A successful scan records check-in on the first scan and check-out on the next accepted scan of that employee's daily QR. The log updates from the scan response without a page refresh. A prominent check/cross overlay and fixed top notification report the result.

## Hidden Administrator settings

Press **Ctrl+0**. The browser shortcut is intercepted on the kiosk page and WorkTrack asks for the password of the Administrator who activated the kiosk. After reauthentication, settings are unlocked for 10 minutes. Available actions:

- Select/refresh a camera device and restart the scanner.
- Record a manual punch or correct an existing attendance record.
- Exit kiosk mode. Exit requires the activating Administrator's password again.

In the kiosk, press **Ctrl+0**, enter the activating Administrator’s password, and open **Manual attendance**. Enter the employee ID, choose **Check in** or **Check out**, and select **Record attendance**. WorkTrack records the current time and the Administrator responsible.

## Security boundary

The active kiosk session is tied to the Administrator user ID. Django middleware redirects other WorkTrack application routes to the scanner. Settings and scan endpoints verify the active Administrator session; settings actions also require recent password reauthentication. Failed activation/settings/exit passwords are rate limited.

These controls cannot prevent someone from physically closing the browser, using operating-system shortcuts that the browser intercepts first, switching Windows applications, or powering down the laptop. For a shared terminal, use a separate standard Windows account and configure Windows Assigned Access (or equivalent OS kiosk mode). Keep the Administrator password private and do not leave the settings panel unlocked.

## Camera and network

Camera access requires localhost during local demos or HTTPS in a network deployment. The pinned ZXing UMD build is fetched from jsDelivr with an unpkg fallback, so confirm the demo network permits those hosts. The browser requests continuous autofocus/exposure/white balance when supported; a mild negative exposure compensation is applied if supported. For persistent glare, reduce phone display brightness and tilt the screen slightly to avoid reflections.


## Correct a record

Open **Correct attendance** in the unlocked settings. Enter the employee ID, choose the date and select **Find record**. Confirm the displayed employee and date.

- For an early check-out, select **Clear accidental check-out**, enter the reason and select **Save correction**. The original check-in stays on the record. The employee can scan again when leaving that day.
- For incorrect punches, enter the correct times and daily attendance status, give a reason and save.
- For an entirely mistaken record, enter a reason, select **Delete record** and confirm the employee and date. The audit trail retains the previous values, reason and Administrator.

If another scan or correction changes the record, find it again to review the latest times. Approved full-day leave is managed through the leave workflow. On an approved half day, keep **Half Day** when correcting punches.
