function Test-TemporaryTunnelHost {
  param([string]$HostName)

  $HostLower = if ($null -eq $HostName) { "" } else { $HostName.Trim().TrimEnd(".").ToLowerInvariant() }
  if (-not $HostLower) {
    return $false
  }
  return (
    $HostLower -eq "loca.lt" -or
    $HostLower -like "*.loca.lt" -or
    $HostLower -eq "trycloudflare.com" -or
    $HostLower -like "*.trycloudflare.com"
  )
}

function Test-PrivateOrLocalHost {
  param([string]$HostName)

  $HostLower = if ($null -eq $HostName) { "" } else { $HostName.Trim().Trim([char[]]"[]").TrimEnd(".").ToLowerInvariant() }
  if (-not $HostLower) {
    return $true
  }

  if ($HostLower -in @("localhost", "0.0.0.0", "::1", "host.docker.internal")) {
    return $true
  }
  if ($HostLower -like "*.localhost" -or $HostLower -like "*.local" -or $HostLower -like "*.localdomain") {
    return $true
  }
  if ($HostLower -notmatch "\." -and $HostLower -notmatch ":") {
    return $true
  }

  $Address = $null
  if ([System.Net.IPAddress]::TryParse($HostLower, [ref]$Address)) {
    if ([System.Net.IPAddress]::IsLoopback($Address)) {
      return $true
    }

    $Bytes = $Address.GetAddressBytes()
    if ($Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) {
      return (
        $Bytes[0] -eq 10 -or
        $Bytes[0] -eq 127 -or
        ($Bytes[0] -eq 169 -and $Bytes[1] -eq 254) -or
        ($Bytes[0] -eq 172 -and $Bytes[1] -ge 16 -and $Bytes[1] -le 31) -or
        ($Bytes[0] -eq 192 -and $Bytes[1] -eq 168) -or
        ($Bytes[0] -eq 0)
      )
    }

    if ($Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetworkV6) {
      $FirstByte = [int]$Bytes[0]
      return (
        $Address.IsIPv6LinkLocal -or
        $Address.IsIPv6SiteLocal -or
        (($FirstByte -band 0xfe) -eq 0xfc)
      )
    }
  }

  return $false
}

function Assert-PermanentCloudApiUrl {
  param(
    [Parameter(Mandatory = $true)][string]$Value,
    [string]$Purpose = "Permanent cloud API"
  )

  $Trimmed = $Value.Trim().TrimEnd("/")
  if (-not $Trimmed) {
    throw "$Purpose URL cannot be empty."
  }

  $Uri = $null
  if (-not [System.Uri]::TryCreate($Trimmed, [System.UriKind]::Absolute, [ref]$Uri)) {
    throw "$Purpose URL must be absolute, for example https://your-api.onrender.com"
  }

  if ($Uri.Scheme -ne "https") {
    throw "$Purpose URL must use public https."
  }

  if (Test-TemporaryTunnelHost -HostName $Uri.Host) {
    throw "$Purpose URL cannot be a temporary tunnel domain (*.loca.lt or *.trycloudflare.com)."
  }

  if (Test-PrivateOrLocalHost -HostName $Uri.Host) {
    throw "$Purpose URL must be a real public cloud host, not localhost, .local, a single-label host, or a private IP such as 10.x.x.x, 172.16-31.x.x, or 192.168.x.x."
  }

  return $Trimmed
}
