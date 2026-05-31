[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$ApiBaseUrl
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "cloud_url_policy.ps1")
$ApiBaseUrl = Assert-PermanentCloudApiUrl -Value $ApiBaseUrl -Purpose "Render API"

$Health = Invoke-RestMethod -Uri "$ApiBaseUrl/health" -TimeoutSec 45
$Ready = Invoke-RestMethod -Uri "$ApiBaseUrl/ready" -TimeoutSec 45
$TrueFact = Invoke-RestMethod `
  -Uri "$ApiBaseUrl/factcheck" `
  -Method Post `
  -ContentType "application/json" `
  -Body (@{ text = "Elephants are mammals." } | ConvertTo-Json -Compress) `
  -TimeoutSec 90
$FakeFact = Invoke-RestMethod `
  -Uri "$ApiBaseUrl/factcheck" `
  -Method Post `
  -ContentType "application/json" `
  -Body (@{ text = "Elephants are insects." } | ConvertTo-Json -Compress) `
  -TimeoutSec 90

[pscustomobject]@{
  Api = $ApiBaseUrl
  Health = $Health.status
  Ready = $Ready.status
  TrueProbe = "$($TrueFact.verdict) / $($TrueFact.confidence)"
  FakeProbe = "$($FakeFact.verdict) / $($FakeFact.confidence)"
}
