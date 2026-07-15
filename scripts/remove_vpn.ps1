<#
    Remove uma conexão VPN existente.
    Entrada (JSON): { name, all_users }
    Saída (JSON): { success, error, data }
#>
param(
    [Parameter(Mandatory = $true)][string]$InputJson,
    [Parameter(Mandatory = $true)][string]$OutputJson
)

$ErrorActionPreference = 'Stop'
$result = @{ success = $false; error = $null; data = $null }

try {
    $in = Get-Content -Raw -Path $InputJson | ConvertFrom-Json
    Remove-VpnConnection -Name $in.name -AllUserConnection:([bool]$in.all_users) -Force -Confirm:$false -ErrorAction Stop
    $result.success = $true
    $result.data = @{ name = $in.name }
} catch {
    $result.success = $false
    $result.error = $_.Exception.Message
}

$result | ConvertTo-Json -Depth 4 -Compress | Out-File -FilePath $OutputJson -Encoding utf8
if ($result.success) { exit 0 } else { exit 1 }
