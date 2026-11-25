# WorkTrack QR kiosk camera guide

## Current scanner

The kiosk uses `@zxing/browser` 0.2.1. It decodes each camera frame in up to three ways:

1. The original camera frame.
2. A centered crop with grayscale tonal normalization and mild edge sharpening.
3. A high-contrast, Otsu-thresholded version of that crop.

The kiosk also requests a higher-resolution video stream, enables continuous autofocus and auto-exposure when the camera exposes those capabilities, and provides camera selection only in the password-protected Administrator settings. Exposure, focus, and white balance are adjusted automatically where supported.

## Recommended scanning setup

- Open the kiosk on the laptop using `http://127.0.0.1:8000` during local development or HTTPS in production.
- Use a current version of Chrome or Edge and allow camera access.
- Close applications that may already be using the webcam.
- Clean the webcam lens and select the clearest camera in the Camera device menu.
- Display the employee QR at its full size. Do not zoom the web page out or crop the QR image.
- Keep phone brightness around 40–60% as a starting point. Increase or decrease it based on the laptop camera preview.
- Avoid reflections and strong overhead light on the phone glass.
- Hold the phone parallel to the camera, place the QR inside the center guide, and keep it steady for a moment.
- The scanner applies a gentle negative exposure compensation automatically when supported. If the image is still washed out, lower phone brightness and change the angle to avoid reflections; the kiosk no longer shows manual glare/exposure controls.
- If a Zoom control is available, increase it only enough for the QR to fill most of the guide while leaving its full border visible.

## After each scan

After a successful scan, the kiosk stays active and accepts a different employee QR automatically. Repeated frames of the same token are ignored. To scan the same employee's QR again later for check-out, remove it from the camera view until the scanner detects that it is gone; the token is then automatically re-armed. The attendance table updates immediately after each successful scan without refreshing the page.

## If the QR still cannot be read

1. Stop and restart the camera.
2. Select a different webcam if one is available.
3. Refresh the camera list after granting permission.
4. Reduce phone brightness and remove screen reflections.
5. Move the phone slightly farther away if it is too close for the webcam's focus range, then keep the QR centered.
6. In the kiosk, press **Ctrl+0**, enter the activating Administrator’s password, and open **Manual attendance**. Enter the employee ID, choose **Check in** or **Check out**, and select **Record attendance**. WorkTrack records the current time and the Administrator responsible.

Image processing can improve mild softness and contrast, but it cannot recreate finder patterns or QR modules that are severely out of focus, motion-blurred, clipped to pure white by overexposure, or displayed too small. If the built-in webcam remains unreliable in a real office, use a USB 2D imager that explicitly supports reading QR codes from phone displays.

## Security and data handling

ZXing decodes the QR in the kiosk browser. The decoded text is sent to the existing Django kiosk endpoint over the authenticated session with CSRF protection. Django remains authoritative: it verifies the signed employee-specific daily token, checks that it has not expired, applies attendance rules, and writes the audit trail. The QR decoder does not decide employee identity or write attendance directly.

No database schema change is required for this scanner update.
