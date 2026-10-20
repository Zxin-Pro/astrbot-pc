# 一条命令出 exe + 发布用 zip：
#   powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
#
# 产物：
#   dist\AstrBotPC\AstrBotPC.exe            可直接双击
#   dist\AstrBotPC-<版本>-win64.zip         发给别人 / 传 Release
#
# 注意：这个文件必须存成 UTF-8 with BOM。Windows PowerShell 5.1 读无 BOM 的
# 中文脚本会按 ANSI 解码，引号会被吃掉，报 "string is missing the terminator"。

param(
  [string]$Version = '1.0.0'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

Write-Host '[1/4] gen icon'
python tools\make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'icon failed' }

Write-Host '[2/4] clean'
Remove-Item -Recurse -Force .build, dist -ErrorAction SilentlyContinue

Write-Host '[3/4] pyinstaller'
python -m PyInstaller build.spec --noconfirm --clean --workpath .build --distpath dist
if ($LASTEXITCODE -ne 0) { throw 'build failed, see log above' }

Write-Host '[4/4] zip'
$zip = Join-Path $root "dist\AstrBotPC-$Version-win64.zip"
Compress-Archive -Path (Join-Path $root 'dist\AstrBotPC\*') -DestinationPath $zip -Force
$size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "done: $zip ($size MB)"