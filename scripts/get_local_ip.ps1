<#
    Consulta o IPv4 atribuído à interface virtual de uma conexão VPN conectada.
    O InterfaceAlias no Windows é o próprio nome da conexão (não confundir com
    o campo "Device" do rasphone.pbk, que é o tipo de miniporte WAN).
    Entrada (JSON): { interface_alias }
    Saída (JSON): { success, error, data: { ip: string|null } }
#>
param(
    [Parameter(Mandatory = $true)][string]$InputJson,
    [Parameter(Mandatory = $true)][string]$OutputJson
)

$ErrorActionPreference = 'Stop'
$result = @{ success = $false; error = $null; data = $null }

try {
    $in = Get-Content -Raw -Path $InputJson | ConvertFrom-Json

    $ip = Get-NetIPAddress -InterfaceAlias $in.interface_alias -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.PrefixOrigin -ne 'WellKnown' } |
        Select-Object -First 1 -ExpandProperty IPAddress

    $result.success = $true
    $result.data = @{ ip = $ip }
} catch {
    $result.success = $false
    $result.error = $_.Exception.Message
}

$result | ConvertTo-Json -Depth 4 -Compress | Out-File -FilePath $OutputJson -Encoding utf8
if ($result.success) { exit 0 } else { exit 1 }
