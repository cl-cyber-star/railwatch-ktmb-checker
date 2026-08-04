# Railwatch Session Connector

This unpacked Manifest V3 extension connects the KTMB account already signed in
on `https://online.ktmb.com.my/` to the Railwatch account that generated a
short-lived one-use code.

The extension never reads the KTMB password. It first confirms that the selected
KTMB tab is authenticated, then sends only unexpired KTMB-owned cookies and
local storage over HTTPS to Railwatch. Railwatch encrypts that state before
storing it against the Railwatch user's email.

## Install in Chrome or Edge

1. Unzip the connector package.
2. Open `chrome://extensions` or `edge://extensions`.
3. Enable **Developer mode**.
4. Select **Load unpacked** and choose this `extension` folder.
5. Pin **Railwatch Session Connector**.
6. Generate a one-use code in Railwatch, sign in on the official KTMB page, and
   connect from the extension popup.
