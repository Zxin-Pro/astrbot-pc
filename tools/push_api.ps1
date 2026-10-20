# 通过 GitHub REST API 把一个本地提交推上去，不依赖 git 的 443 通道。
#
# 适用场景：公司/校园网只放行了 api.github.com，而 git push 到 github.com:443
# 会被重置。流程是 blob → tree → commit → ref，和 git 自己做的是一回事。
#
# 用法：
#   $env:GITHUB_TOKEN = 'ghp_xxx'      # 或 github_pat_xxx
#   powershell -ExecutionPolicy Bypass -File tools\push_api.ps1

param(
  [string]$Repo = 'Zxin-Pro/astrbot-pc',
  [string]$Branch = 'main',
  [string]$MessageFile = '.git\COMMIT_MSG_TMP.txt'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$tok = $env:GITHUB_TOKEN
if (-not $tok) { throw 'GITHUB_TOKEN 没有设置' }

$headers = @{
  Authorization = "Bearer $tok"
  'User-Agent'  = 'AstrBotPC-push'
  Accept        = 'application/vnd.github+json'
}
$api = "https://api.github.com/repos/$Repo"

function Post-Json([string]$uri, $obj) {
  $json = $obj | ConvertTo-Json -Compress -Depth 20
  $bytes = [Text.Encoding]::UTF8.GetBytes($json)
  return Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -Body $bytes `
    -ContentType 'application/json; charset=utf-8' -TimeoutSec 60
}

$files = git ls-files
if (-not $files) { throw 'git ls-files 是空的，先在本地提交' }
Write-Host "files: $($files.Count)"

$entries = @()
$i = 0
foreach ($f in $files) {
  $i++
  $path = Join-Path $root $f
  $b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($path))
  $blob = Post-Json "$api/git/blobs" @{ content = $b64; encoding = 'base64' }
  $entries += @{ path = $f.Replace('\', '/'); mode = '100644'; type = 'blob'; sha = $blob.sha }
  if ($i % 10 -eq 0 -or $i -eq $files.Count) { Write-Host "  blob $i/$($files.Count)" }
}

$tree = Post-Json "$api/git/trees" @{ tree = $entries }
Write-Host "tree: $($tree.sha)"

$message = [IO.File]::ReadAllText((Join-Path $root $MessageFile), [Text.Encoding]::UTF8)

# 空仓库没有 parent；已经有初始提交就接上去，历史保持一条直线
$parents = @()
try {
  $head = Invoke-RestMethod -Uri "$api/git/ref/heads/$Branch" -Headers $headers -TimeoutSec 30
  $parents = @($head.object.sha)
  Write-Host "parent: $($head.object.sha)"
} catch {
  Write-Host 'parent: (空仓库，做根提交)'
}

$commit = Post-Json "$api/git/commits" @{ message = $message; tree = $tree.sha; parents = $parents }
Write-Host "commit: $($commit.sha)"

# 空仓库没有 ref，先建；已有就更新（分支已存在时会 422，退回 PATCH）
try {
  $ref = Post-Json "$api/git/refs" @{ ref = "refs/heads/$Branch"; sha = $commit.sha }
  Write-Host "ref created: $($ref.ref)"
} catch {
  $body = [Text.Encoding]::UTF8.GetBytes((@{ sha = $commit.sha; force = $true } | ConvertTo-Json -Compress))
  $ref = Invoke-RestMethod -Method Patch -Uri "$api/git/refs/heads/$Branch" -Headers $headers `
    -Body $body -ContentType 'application/json; charset=utf-8' -TimeoutSec 60
  Write-Host "ref updated: $($ref.ref)"
}

Write-Host "PUSH_OK $($commit.sha)"
