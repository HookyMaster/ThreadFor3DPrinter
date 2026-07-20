# Fusion 360 3D Printable Thread Generator

[![Release](https://img.shields.io/github/v/release/HookyMaster/ThreadFor3DPrinter)](https://github.com/HookyMaster/ThreadFor3DPrinter/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Platform](https://img.shields.io/badge/Autodesk-Fusion-orange)

[中文说明](README.zh-CN.md) · [Download the latest release](https://github.com/HookyMaster/ThreadFor3DPrinter/releases/latest/download/ThreadFor3DPrinter-v1.0.0.zip)

<img src="icon-v4.png" alt="Fusion 360 add-in for generating 3D-printable internal and external trapezoidal threads" width="160">

**ThreadFor3DPrinter** is an Autodesk Fusion add-in that generates coarse trapezoidal **internal and external threads for 3D printing**. Select a cylindrical face and the add-in automatically detects whether it belongs to a bolt or a nut/hole.

## Features

- Generates both external bolt threads and internal nut/hole threads.
- Uses a 3D-printing-friendly trapezoidal profile with fixed **45-degree flanks**.
- Automatically detects internal and external cylindrical faces.
- Provides adjustable tooth width, thread height, sampling resolution, and end offset.
- Supports Autodesk Fusion on Windows and macOS.

## Files required for installation

Keep these three files together in one folder:

```text
ThreadFor3DPrinter/
├── ThreadFor3DPrinter.py
├── ThreadFor3DPrinter.manifest
└── icon-v4.png
```

The manifest uses `icon-v4.png` as the icon shown in Fusion's **Scripts and Add-Ins** dialog.

## Installation

### Windows

Copy the complete `ThreadFor3DPrinter` folder to:

```text
%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\
```

### macOS

Copy the complete `ThreadFor3DPrinter` folder to:

```text
~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/
```

Alternatively, open **Utilities > Add-Ins > Scripts and Add-Ins**, select the **Add-Ins** tab, click the green **+** button, and select the `ThreadFor3DPrinter` folder.

## Starting the add-in

1. Open Fusion and switch to the **Design** workspace.
2. Open **Utilities > Add-Ins > Scripts and Add-Ins**.
3. Select the **Add-Ins** tab.
4. Select **ThreadFor3DPrinter** and click **Run**.
5. The **ThreadFor3DPrinter** command appears in the **Solid > Create** panel.

Enable **Run on Startup** in the Add-Ins dialog if you want it loaded automatically whenever Fusion starts.

## Preparing the model

- For an external thread, create a solid cylinder and select its outside cylindrical face.
- For an internal thread, create a cylindrical hole and select its inside cylindrical face.
- The target must be a true cylindrical BRep face. Conical, mesh, faceted, or arbitrary curved faces are not supported.
- Leave enough axial length for the selected thread dimensions and end offset.

## Operation

1. Run **ThreadFor3DPrinter** from **Solid > Create**.
2. Click **Cylindrical / hole face**, then select exactly one cylindrical face.
3. Confirm the detected type in the calculation area:
   - **External thread (bolt):** the profile grows outward.
   - **Internal thread (nut):** the profile grows inward.
4. Set the thread parameters:
   - **Long edge L (tooth width):** axial width of the trapezoidal profile. Default: `8 mm`.
   - **Trapezoid height H:** radial thread depth/height. Default: `3 mm`. The profile uses the same distance `H` in the axial direction at each side, producing a fixed **45° thread flank angle**.
   - **Points per turn:** helix sampling resolution. Default: `16`; minimum: `4`.
   - **End offset:** distance between the cylinder end and the start of the helix. Default: `5 mm`.
5. Review the automatically calculated short edge, pitch, turn count, helix height, cylinder size, and detected thread type.
6. Click **OK** to generate the helical path, trapezoidal profile, and swept thread body.

## Parameter rules

The add-in calculates:

```text
Short edge S = L - 2H
Pitch P      = L + S = 2(L - H)
```

The trapezoidal tooth has a **45° flank on each side**. This angle is fixed by the script and is not an adjustable input. Here, 45° means the angle between either sloped tooth flank and the thread axis; equivalently, it is also 45° to the radial direction.

Inputs must satisfy:

- `L > 0`
- `H > 0`
- `L - 2H > 0`
- For an internal thread, `H` must be smaller than the hole radius.

The add-in reserves approximately one full turn of axial space. The generated number of turns may therefore be lower than the simple cylinder-length/pitch ratio.

## After generation

The sweep is created as a **new body**. Use Fusion's **Combine** command to:

- **Join** it to the cylinder for an external thread.
- **Join** it to the surrounding part for an internal thread as well.

For reliable 3D-printed mating parts, add clearance appropriate to your printer, material, layer height, and nozzle size. Test with a short sample before printing the final part.

## Troubleshooting

- **The OK button is disabled:** select exactly one cylindrical face and verify the parameter rules above.
- **Internal thread depth warning:** reduce `H` so it is smaller than the hole radius.
- **The command is missing:** run the add-in again from **Scripts and Add-Ins**, or restart Fusion.
- **The icon does not update:** close and reopen the **Scripts and Add-Ins** dialog, or restart Fusion.
- **The thread looks faceted:** increase **Points per turn**. Higher values produce more geometry and may take longer; the script caps the total helix samples at 400.
- **Sweep failure:** use a simpler cylindrical body, reduce the thread dimensions, increase available axial length, or increase the end offset.

## Uninstalling

Stop the add-in in **Scripts and Add-Ins**, close Fusion, and remove the `ThreadFor3DPrinter` folder from the AddIns directory.
