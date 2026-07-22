# Autodesk Marketplace submission sheet

## Product

- Product name: ThreadFor3DPrinter
- Version: 1.0.1
- Autodesk product: Fusion
- App type: Add-in
- Operating systems: Windows 64-bit and macOS
- Pricing: Free
- Publisher: HookyMaster
- Source/project URL: https://github.com/HookyMaster/ThreadFor3DPrinter
- Support URL: https://github.com/HookyMaster/ThreadFor3DPrinter/issues
- Privacy policy: https://github.com/HookyMaster/ThreadFor3DPrinter/blob/master/docs/PRIVACY.md
- License: GNU GPL v3

## Short description

Generate 3D-printing-friendly internal and external trapezoidal threads from cylindrical faces in Autodesk Fusion.

## Full description

ThreadFor3DPrinter generates coarse trapezoidal thread geometry designed for 3D-printed parts. Select a cylindrical outer face or a cylindrical hole face and the add-in automatically identifies whether an external or internal thread is required.

Users can adjust tooth width, radial thread height, helix sampling resolution, and end offset. The add-in displays the calculated pitch, turn count, cylinder dimensions, and detected thread type before creating the geometry. The resulting sweep is created as a separate body so users retain control over the final Combine operation and printing clearance.

Key features:

- Internal and external thread generation
- Automatic cylindrical-face type detection
- 45-degree trapezoidal flanks suitable for additive manufacturing
- Adjustable dimensions and sampling resolution
- Local processing with no data collection or network communication
- Windows and macOS support

## Trial / licensing

No activation, account, subscription, or license key is required. The add-in is fully functional after installation.

## Installation and start

Install using the Autodesk Marketplace installer. Restart Fusion if it was open during installation. The command starts automatically and appears under Solid > Create > ThreadFor3DPrinter.

## Uninstallation

Close Fusion, then uninstall ThreadFor3DPrinter using the operating system's installed-apps interface.

## Reviewer test procedure

1. Start Fusion and create a new Design document.
2. Create a solid cylinder at least 30 mm in diameter and 60 mm long.
3. Run Solid > Create > ThreadFor3DPrinter.
4. Select the outside cylindrical face.
5. Use defaults: L = 8 mm, H = 3 mm, points per turn = 16, offset = 5 mm.
6. Confirm the add-in reports an external thread, then choose OK.
7. Verify a separate swept thread body is created without errors.
8. Create a second body with a cylindrical hole and repeat using the inside cylindrical face.
9. Verify the add-in reports an internal thread and creates a separate thread body.

## Assets to upload

- App icon: `icon-v4.png`
- External-thread screenshot: `docs/images/fusion-360-external-thread-generator.png`
- Internal-thread screenshot: `docs/images/fusion-360-internal-thread-generator.png`
- Section-view screenshot: `docs/images/internal-external-thread-section.png`
- Submission package: `dist/ThreadFor3DPrinter-Marketplace-1.0.1.zip`

## Publisher fields that require the account owner

Before submission, enter a monitored support email address, legal publisher name/address, tax/payment information if requested, and the exact supported Fusion release selection shown by the Publisher Corner form.
