using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

namespace BonjurLauncher
{
    internal sealed class LauncherForm : Form
    {
        private static readonly string AppVersion = ReadAssemblyVersion();
        private const string ResourceName   = "BonjurLauncher.app.zip";
        private const string AppEntry       = "main.py";
        private const string AppName        = "bonjour epta";

        private static string ReadAssemblyVersion()
        {
            try
            {
                var info = Assembly.GetExecutingAssembly()
                    .GetCustomAttribute<AssemblyInformationalVersionAttribute>()
                    ?.InformationalVersion;
                if (!string.IsNullOrWhiteSpace(info))
                {
                    int plus = info.IndexOf('+');
                    return (plus >= 0 ? info.Substring(0, plus) : info).Trim();
                }
            }
            catch { }
            try
            {
                var v = Application.ProductVersion ?? "";
                int plus = v.IndexOf('+');
                if (v.Length > 0) return (plus >= 0 ? v.Substring(0, plus) : v).Trim();
            }
            catch { }
            return "0.0.0";
        }

        private static readonly Color BG     = Color.FromArgb(0xF2, 0xF2, 0xEF);
        private static readonly Color INK    = Color.FromArgb(0x14, 0x14, 0x14);
        private static readonly Color MUTED  = Color.FromArgb(0x8E, 0x8E, 0x86);
        private static readonly Color ACCENT = Color.FromArgb(0x11, 0x11, 0x11);
        private static readonly Color BORDER = Color.FromArgb(0xE2, 0xE2, 0xDC);
        private static readonly Color ERR    = Color.FromArgb(0xB4, 0x23, 0x18);

        private readonly Label       _lblStatus;
        private readonly ProgressBar _bar;
        private readonly Button      _btnClose;

        private bool  _dragging;
        private Point _dragStart;

        public LauncherForm()
        {
            SuspendLayout();

            Text            = $"{AppName} v{AppVersion}";
            FormBorderStyle = FormBorderStyle.None;
            BackColor       = BG;
            ForeColor       = INK;
            ClientSize      = new Size(460, 130);
            StartPosition   = FormStartPosition.CenterScreen;
            DoubleBuffered  = true;

            var lblTitle = new Label
            {
                Text      = $"{AppName}   v{AppVersion}",
                Font      = new Font("Segoe UI", 11f, FontStyle.Bold),
                ForeColor = INK,
                BackColor = BG,
                AutoSize  = true,
                Location  = new Point(18, 16),
            };

            _lblStatus = new Label
            {
                Text      = "Запуск...",
                Font      = new Font("Segoe UI", 9f),
                ForeColor = MUTED,
                BackColor = BG,
                AutoSize  = false,
                Size      = new Size(422, 22),
                Location  = new Point(18, 60),
            };

            _bar = new ProgressBar
            {
                Style    = ProgressBarStyle.Continuous,
                Size     = new Size(422, 5),
                Location = new Point(18, 90),
                Minimum  = 0,
                Maximum  = 100,
                Value    = 0,
                ForeColor = ACCENT,
            };

            _btnClose = new Button
            {
                Text      = "✕",
                Font      = new Font("Segoe UI", 13f),
                ForeColor = MUTED,
                BackColor = BG,
                FlatStyle = FlatStyle.Flat,
                Size      = new Size(38, 34),
                Location  = new Point(ClientSize.Width - 44, 4),
                Visible   = false,
            };
            _btnClose.FlatAppearance.BorderSize = 0;
            _btnClose.Click += (s, e) => Application.Exit();

            Controls.AddRange(new Control[] { lblTitle, _lblStatus, _bar, _btnClose });

            MouseDown += (s, e) => { _dragging = true;  _dragStart = e.Location; };
            MouseMove += (s, e) => { if (_dragging) Location = new Point(Location.X + e.X - _dragStart.X, Location.Y + e.Y - _dragStart.Y); };
            MouseUp   += (s, e) => _dragging = false;

            Paint += (s, e) => {
                using (var p = new Pen(BORDER))
                    e.Graphics.DrawRectangle(p, 0, 0, ClientSize.Width - 1, ClientSize.Height - 1);
            };

            ResumeLayout(false);
        }

        protected override void OnShown(EventArgs e)
        {
            base.OnShown(e);
            Task.Run(() => RunAsync());
        }

        private void SetStatus(string msg, int pct = -1)
        {
            if (InvokeRequired) { Invoke(new Action(() => SetStatus(msg, pct))); return; }
            _lblStatus.Text = msg;
            if (pct >= 0) _bar.Value = Math.Min(pct, 100);
        }

        private void ShowError(string msg)
        {
            if (InvokeRequired) { Invoke(new Action(() => ShowError(msg))); return; }
            _lblStatus.Text      = msg;
            _lblStatus.ForeColor = ERR;
            _btnClose.Visible    = true;
        }

        private void CloseApp()
        {
            if (InvokeRequired) { Invoke(new Action(CloseApp)); return; }
            Application.Exit();
        }

        private async Task RunAsync()
        {
            try
            {
                // Always install/run next to this exe (Total Commander workflow).
                string installDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
                if (string.IsNullOrEmpty(installDir))
                {
                    ShowError("Не удалось определить папку установщика.");
                    return;
                }

                bool needInstall = !File.Exists(Path.Combine(installDir, AppEntry))
                    || !IsInstalledVersion(installDir, AppVersion);

                if (!needInstall)
                {
                    SetStatus("Запускаю...", 100);
                    string python = await EnsurePython();
                    if (python == null) { ShowError("Python не найден. Установите Python 3.12 вручную."); return; }
                    await Task.Delay(200);
                    LaunchApp(python, Path.Combine(installDir, AppEntry));
                    return;
                }

                // First run / upgrade in this folder
                SetStatus("Проверяю Python 3.12...", 5);
                string py = await EnsurePython(progress: p => SetStatus(
                    "Устанавливаю Python 3.12 через winget... " + p + "%",
                    5 + p * 25 / 100));
                if (py == null) { ShowError("Не удалось установить Python. Установите вручную: winget install Python.Python.3.12"); return; }
                SetStatus("Python — готов.", 32);

                SetStatus("Устанавливаю bonjour epta v" + AppVersion + "...", 36);
                await Task.Run(() => ExtractEmbeddedWithRetry(ResourceName, installDir,
                    pct => SetStatus("Распаковка... " + pct + "%", 36 + pct * 30 / 100)));
                File.WriteAllText(Path.Combine(installDir, "VERSION"), AppVersion);
                SetStatus("Приложение распаковано.", 66);

                SetStatus("Устанавливаю зависимости (pip)...", 68);
                bool depsOk = await PipInstall(py, Path.Combine(installDir, "requirements.txt"),
                    p => SetStatus("Зависимости... " + p + "%", 68 + p * 28 / 100));
                if (!depsOk) { ShowError("Не удалось установить зависимости. Проверьте интернет."); return; }
                SetStatus("Готово. Запускаю...", 100);
                await Task.Delay(300);
                LaunchApp(py, Path.Combine(installDir, AppEntry));
            }
            catch (Exception ex)
            {
                ShowError("Ошибка: " + ex.Message);
            }
        }

        // ── helpers ───────────────────────────────────────────────

        private static bool IsInstalledVersion(string installDir, string expected)
        {
            try
            {
                string vf = Path.Combine(installDir, "VERSION");
                if (!File.Exists(vf)) return false;
                return File.ReadAllLines(vf)[0].Trim().StartsWith(expected, StringComparison.OrdinalIgnoreCase);
            }
            catch { return false; }
        }

        private static string FindPython()
        {
            // 1. py launcher
            try
            {
                var psi = new ProcessStartInfo("py", "-3.12 -c \"import sys;print(sys.executable)\"")
                {
                    RedirectStandardOutput = true, UseShellExecute = false, CreateNoWindow = true,
                };
                using (var p = Process.Start(psi))
                {
                    string outp = p.StandardOutput.ReadToEnd().Trim();
                    p.WaitForExit();
                    if (p.ExitCode == 0 && File.Exists(outp)) return outp;
                }
            }
            catch { }
            // 2. python on PATH
            try
            {
                foreach (var name in new[] { "pythonw.exe", "python.exe" })
                {
                    string found = SearchPath(name);
                    if (found != null) return found;
                }
            }
            catch { }
            // 3. well-known winget install location
            var cand = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Python", "Python312", "pythonw.exe");
            return File.Exists(cand) ? cand : null;
        }

        private static string SearchPath(string exe)
        {
            try
            {
                var psi = new ProcessStartInfo("where", exe)
                { RedirectStandardOutput = true, UseShellExecute = false, CreateNoWindow = true };
                using (var p = Process.Start(psi))
                {
                    string outp = p.StandardOutput.ReadToEnd().Trim();
                    p.WaitForExit();
                    var first = outp.Split(new[] { "\r\n", "\n" }, StringSplitOptions.RemoveEmptyEntries);
                    if (first.Length > 0 && File.Exists(first[0])) return first[0];
                }
            }
            catch { }
            return null;
        }

        private static async Task<string> EnsurePython(Action<int> progress = null)
        {
            string py = FindPython();
            if (py != null) return py;
            bool ok = await InstallWinget("Python.Python.3.12", progress);
            if (!ok) return null;
            await Task.Delay(500);
            return FindPython();
        }

        private static async Task<bool> InstallWinget(string id, Action<int> progress = null)
        {
            return await Task.Run(() => {
                try
                {
                    var psi = new ProcessStartInfo("winget",
                        $"install --id {id} --silent --accept-source-agreements --accept-package-agreements")
                    {
                        UseShellExecute = false,
                        CreateNoWindow  = true,
                        RedirectStandardOutput = true,
                        RedirectStandardError  = true,
                    };
                    using (var p = Process.Start(psi))
                    {
                        // best-effort progress from stdout lines
                        Task.Run(() => {
                            try { string line; int pct = 0;
                                while ((line = p.StandardOutput.ReadLine()) != null)
                                {
                                    if (line.Contains("%") && progress != null)
                                    {
                                        int start = line.IndexOf('%');
                                        int i = start - 1; while (i >= 0 && char.IsDigit(line[i])) i--;
                                        if (int.TryParse(line.Substring(i + 1, start - i - 1), out int v)) { pct = v; progress(pct); }
                                    }
                                }
                            } catch { }
                        });
                        p.WaitForExit();
                        return p.ExitCode == 0;
                    }
                }
                catch { return false; }
            });
        }

        private static async Task<bool> PipInstall(string pythonw, string requirementsPath, Action<int> progress)
        {
            // use python.exe (not pythonw) to run pip with console output
            string pyExe = pythonw.Replace("pythonw.exe", "python.exe");
            if (!File.Exists(pyExe)) pyExe = pythonw;
            return await Task.Run(() => {
                try
                {
                    var psi = new ProcessStartInfo(pyExe,
                        $"-m pip install -r \"{requirementsPath}\" --disable-pip-version-check --no-warn-script-location")
                    {
                        UseShellExecute = false,
                        CreateNoWindow  = true,
                        RedirectStandardOutput = true,
                        RedirectStandardError  = true,
                    };
                    using (var p = Process.Start(psi))
                    {
                        int lines = 0;
                        Task.Run(() => { try { string l; while ((l = p.StandardOutput.ReadLine()) != null) { lines++; if (progress != null) progress(Math.Min(95, lines * 3)); } } catch { } });
                        p.WaitForExit();
                        if (progress != null) progress(100);
                        return p.ExitCode == 0;
                    }
                }
                catch { return false; }
            });
        }

        private static void ExtractEmbeddedWithRetry(string resourceName, string destDir, Action<int> progress)
        {
            const int maxAttempts = 5;
            Exception last = null;
            for (int attempt = 1; attempt <= maxAttempts; attempt++)
            {
                try { ExtractEmbedded(resourceName, destDir, progress); return; }
                catch (IOException ex) { last = ex; }
                catch (UnauthorizedAccessException ex) { last = ex; }
                System.Threading.Thread.Sleep(400 * attempt);
            }
            throw new IOException("Не удалось распаковать файлы.", last);
        }

        private static void ExtractEmbedded(string resourceName, string destDir, Action<int> progress)
        {
            using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(resourceName))
            {
                if (stream == null)
                    throw new InvalidOperationException($"Embedded resource '{resourceName}' not found.");
                string tmp = Path.Combine(Path.GetTempPath(), "bj_" + Guid.NewGuid().ToString("N").Substring(0, 8) + ".zip");
                try
                {
                    using (var fs = File.Create(tmp))
                    {
                        byte[] buf = new byte[65536];
                        long total = stream.Length, done = 0; int read;
                        while ((read = stream.Read(buf, 0, buf.Length)) > 0)
                        { fs.Write(buf, 0, read); done += read; progress((int)(done * 100 / total)); }
                    }
                    ExtractZip(tmp, destDir);
                }
                finally { try { File.Delete(tmp); } catch { } }
            }
        }

        private static void ExtractZip(string zipPath, string destDir)
        {
            using (var archive = ZipFile.OpenRead(zipPath))
                foreach (var entry in archive.Entries)
                {
                    string fullDest = Path.Combine(destDir, entry.FullName.Replace('/', Path.DirectorySeparatorChar));
                    string dir = Path.GetDirectoryName(fullDest);
                    if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
                    if (!string.IsNullOrEmpty(entry.Name)) entry.ExtractToFile(fullDest, overwrite: true);
                }
        }

        private void LaunchApp(string pythonw, string mainPy)
        {
            try
            {
                var psi = new ProcessStartInfo(pythonw, $"\"{mainPy}\"")
                {
                    UseShellExecute = false,
                    WorkingDirectory = Path.GetDirectoryName(mainPy),
                };
                Process.Start(psi);
            }
            catch { }
            CloseApp();
        }
    }
}
