# Baixa o ChromeDriver compatível com o Google Chrome instalado (Chrome for Testing)
# e salva em .\drivers\chromedriver.exe, caminho usado pelos scripts "npm run scan".
#
# Uso (terminal do VSCode):  powershell -ExecutionPolicy Bypass -File .\baixar_chromedriver.ps1

$ErrorActionPreference = "Stop"
# No Windows PowerShell 5.1 a barra de progresso deixa o download muito lento.
$ProgressPreference = "SilentlyContinue"

$chrome = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { throw "Google Chrome nao encontrado." }

$versao = (Get-Item $chrome).VersionInfo.ProductVersion
$build = ($versao -split "\.")[0..2] -join "."
Write-Host "Chrome instalado: $versao (build $build)"

$indice = Invoke-RestMethod -UseBasicParsing "https://googlechromelabs.github.io/chrome-for-testing/latest-patch-versions-per-build-with-downloads.json"
$entrada = $indice.builds.$build
if (-not $entrada) { throw "Nenhum ChromeDriver publicado para o build $build." }
$url = ($entrada.downloads.chromedriver | Where-Object platform -eq "win64").url
Write-Host "Baixando ChromeDriver $($entrada.version)..."

$raiz = $PSScriptRoot
$zip = Join-Path $env:TEMP "chromedriver-win64.zip"
$tmp = Join-Path $env:TEMP "chromedriver-win64"
Invoke-WebRequest -UseBasicParsing $url -OutFile $zip
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Expand-Archive $zip -DestinationPath $tmp -Force
New-Item -ItemType Directory -Force (Join-Path $raiz "drivers") | Out-Null
Copy-Item (Join-Path $tmp "chromedriver-win64\chromedriver.exe") (Join-Path $raiz "drivers\chromedriver.exe") -Force
Remove-Item $zip, $tmp -Recurse -Force

& (Join-Path $raiz "drivers\chromedriver.exe") --version
