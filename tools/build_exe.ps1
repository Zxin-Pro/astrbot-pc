# 一条命令出两种 exe + 发布用文件：
#   powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
#
# 产物：
#   dist\AstrBotPC\AstrBotPC.exe                    目录版，双击即用（需带 _internal）
#   dist\AstrBotPC-<版本>-win64.zip                 目录版的压缩包
#   dist\AstrBotPC-<版本>-win64-single.exe          单文件版，拷一个文件就能跑
#
# 注意：这个文件必须存成 UTF-8 with BOM。Windows PowerShell 5.1 读无 BOM 的
# 中文脚本会按 ANSI 解码，引号会被吃掉，报 "string is missing the terminator"。

param(
  [string]$Version = '1.0.0'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

Write-Host '[1/5] gen icon'
python tools\make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'icon failed' }

Write-Host '[2/5] clean'
Remove-Item -Recurse -Force .build, .build-onefile, dist, dist-onefile -ErrorAction SilentlyContinue

Write-Host '[3/5] pyinstaller onedir'
python -m PyInstaller build.spec --noconfirm --clean --workpath .build --distpath dist
if ($LASTEXITCODE -ne 0) { throw 'onedir build failed, see log above' }

Write-Host '[4/5] pyinstaller onefile'
python -m PyInstaller build_onefile.spec --noconfirm --clean --workpath .build-onefile --distpath dist-onefile
if ($LASTEXITCODE -ne 0) { throw 'onefile build failed, see log above' }
Copy-Item (Join-Path $root 'dist-onefile\AstrBotPC.exe') (Join-Path $root "dist\AstrBotPC-$Version-win64-single.exe") -Force

Write-Host '[5/5] zip'
$zip = Join-Path $root "dist\AstrBotPC-$Version-win64.zip"
Compress-Archive -Path (Join-Path $root 'dist\AstrBotPC\*') -DestinationPath $zip -Force
Write-Host 'done:'
Get-ChildItem (Join-Path $root 'dist') -File | ForEach-Object {
  Write-Host ("  {0}  {1} MB" -f $_.Name, [math]::Round($_.Length / 1MB, 1))
}
