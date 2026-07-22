# Marketplace packaging

`ADSK.ThreadFor3DPrinter.bundle` is the Autodesk ApplicationPlugins package. Its generated `Contents` files are copied from the repository root by `build-marketplace.ps1`.

Run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File marketplace/build-marketplace.ps1
```

The script creates `dist/ThreadFor3DPrinter-Marketplace-1.0.3.zip` and `dist/ThreadFor3DPrinter-v1.0.3.zip`, then validates the required bundle files, JSON manifest, and XML package metadata.
