# SchoolFlow Gate 0.2 — attended test build

This APK connects to the isolated fictional Gate trial server; the original SchoolFlow service is unchanged. Its separate trial package can coexist with the previous app. Connection details are delivered privately. Free trial storage can reset after sleep/restart; use fictional identities only.

Camera-based local face enrollment and native YuNet/SFace recognition for the existing SchoolFlow gate API. Device lock protects enrollment/settings; local vectors/credentials are encrypted with Android Keystore. No camera photos or face vectors are sent to the server.

This build requires an operator to verify and confirm a recognized person. It is not certified liveness/anti-spoofing and is debug-signed for fictional trials. Android 8+ ARM64 camera/device testing and production signing are still outstanding. Follow README.md for setup and verify results in web scan history.

Enrollment verifies a presented SchoolFlow identity QR against the same-campus server record. Institute/gate scope pins and deletion-cascaded record bindings prevent old local enrollments from silently attaching to reused codes or numeric IDs. No school key or biometric template is bundled.
