# Desktop app

The desktop app is the full Binderdash interface in a native window, for use on a single machine. It needs no server, Docker or sign-in: it stores its database in your user profile and reads run folders directly from your disk.

## Download and install

Download the file for your platform from the [latest release](https://github.com/Australian-Protein-Design-Initiative/binderdash/releases/latest).

The builds are not code-signed, so macOS and Windows ask you to confirm the first launch.

### Linux

Download `Binderdash-<version>-x86_64.AppImage`, make it executable and run it:

```bash
chmod +x Binderdash-*-x86_64.AppImage
./Binderdash-*-x86_64.AppImage
```

The AppImage needs the system WebKitGTK and GTK 3 libraries (on Debian/Ubuntu: `libwebkit2gtk-4.1-0` and `libgtk-3-0`) and FUSE (`libfuse2`) to mount itself.

### macOS (Apple silicon)

1. Unzip `Binderdash-<version>-macos-arm64.zip`.
2. Double-click `Binderdash.app`.

If macOS blocks the app, right-click it and choose **Open**, or clear the quarantine flag:

```bash
xattr -cr Binderdash.app
```

### Windows

1. Unzip `Binderdash-<version>-win64.zip` anywhere.
2. Run `Binderdash.exe`.

The app uses the Microsoft Edge [WebView2 runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/), which is already installed on current Windows 10 and 11. If SmartScreen warns about an unsigned app, choose **More info**, then **Run anyway**.

!!! warning "If the app does not start"

    An error like `RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize` means Windows has marked the unzipped files as coming from the internet, and .NET will not load the bundled `Python.Runtime.dll` while that mark is on it. Clear the mark and run the app again:

    ```powershell
    Get-ChildItem 'C:\path\to\Binderdash' -Recurse -File | Unblock-File
    ```

    Right-clicking the zip, choosing **Properties** and ticking **Unblock** before unzipping avoids it.

## Loading your runs

1. Open **Ingest Runs** and use **Choose folder** to pick the folder that contains your design runs. The path is saved for future sessions.
2. Scan the folder tree and ingest the runs you want. Binderdash detects RFdiffusion, RFdiffusion3, BindCraft and BoltzGen output layouts.
3. Tick runs in **Select Runs**, then explore them in **Designs**, **Plots** and **Filtering**.

Ingesting imports run results into the app's database without changing or deleting any files in your run folders. Removing a run from Binderdash only deletes the database record; the original files remain on disk.

## Data directory

| OS | Location |
| --- | --- |
| Linux | `$XDG_DATA_HOME/binderdash` or `~/.local/share/binderdash` |
| macOS | `~/Library/Application Support/Binderdash` |
| Windows | `%LOCALAPPDATA%\Binderdash` |

This folder contains `binderdash.sqlite` (the database), `desktop.json` (folder and window settings), and `binderdash.log`. If the app fails to start, check `binderdash.log` first.
