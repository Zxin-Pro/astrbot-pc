# 一条命令出两种 exe + 发布用文件：
#   powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
#
# 产物：
#   dist\AstrBotPC\AstrBotPC.exe                    目录版，双击即用（需带 _internal）
#   dist\AstrBotPC-<版本>-win64.zip                 目录版的压缩包（约 23 MB，部署时联网）
#   dist\AstrBotPC-<版本>-win64-single.exe          单文件版，拷一个文件就能跑
#   dist\AstrBotPC-<版本>-win64-offline.zip         带 resources\ 的离线版（约 280 MB，部署全程不联网）
#
# 离线版只在 resources\ 存在时才出。先跑 python tools\build_offline.py 把资源收齐。
#
# 注意：这个文件必须存成 UTF-8 with BOM。Windows PowerShell 5.1 读无 BOM 的
# 中文脚本会按 ANSI 解码，引号会被吃掉，报 "string is missing the terminator"。

param(
  [string]$Version = '1.0.0'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

# 有的机器上 python 只在注册表里，PATH 里没有（Get-Command 会空手而归），
# 所以先问 PATH，再退到常见安装位置，最后才让命令自己报错。
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) {
  foreach ($cand in @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
    'C:\Python312\python.exe',
    'C:\Python311\python.exe'
  )) { if (Test-Path $cand) { $py = $cand; break } }
}
if (-not $py) { throw '找不到 python.exe：装一个 Python 3.10+ 或者把路径加到 PATH' }
Write-Host "[0/6] python = $py"

Write-Host '[1/6] gen icon'
& $py tools\make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'icon failed' }

Write-Host '[2/6] clean'
Remove-Item -Recurse -Force .build, .build-onefile, dist, dist-onefile -ErrorAction SilentlyContinue

Write-Host '[3/6] pyinstaller onedir'
& $py -m PyInstaller build.spec --noconfirm --clean --workpath .build --distpath dist
if ($LASTEXITCODE -ne 0) { throw 'onedir build failed, see log above' }

Write-Host '[4/6] pyinstaller onefile'
& $py -m PyInstaller build_onefile.spec --noconfirm --clean --workpath .build-onefile --distpath dist-onefile
if ($LASTEXITCODE -ne 0) { throw 'onefile build failed, see log above' }
Copy-Item (Join-Path $root 'dist-onefile\AstrBotPC.exe') (Join-Path $root "dist\AstrBotPC-$Version-win64-single.exe") -Force

Write-Host '[5/6] zip'
$zip = Join-Path $root "dist\AstrBotPC-$Version-win64.zip"
Compress-Archive -Path (Join-Path $root 'dist\AstrBotPC\*') -DestinationPath $zip -Force

Write-Host '[6/6] offline zip'
$res = Join-Path $root 'resources'
if (Test-Path $res) {
  # 资源要摆在 exe 旁边（paths._res_dir 先看 sys.executable\..\resources），
  # 所以直接拷进目录版里再压一次；压完删掉，别让普通版的构建目录一直胖着。
  $dst = Join-Path $root 'dist\AstrBotPC\resources'
  Copy-Item $res $dst -Recurse -Force
  # 里面的 zip 与 wheel 本来就是压缩过的，Fastest 省时间
  Compress-Archive -Path (Join-Path $root 'dist\AstrBotPC\*') `
    -DestinationPath (Join-Path $root "dist\AstrBotPC-$Version-win64-offline.zip") `
    -Force -CompressionLevel Fastest
  Remove-Item $dst -Recurse -Force
} else {
  Write-Host '  没有 resources\，跳过离线版（先跑 python tools\build_offline.py）'
}

Write-Host 'done:'
Get-ChildItem (Join-Path $root 'dist') -File | ForEach-Object {
  Write-Host ("  {0}  {1} MB" -f $_.Name, [math]::Round($_.Length / 1MB, 1))
}
