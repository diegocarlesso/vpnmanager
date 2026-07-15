<#
    Lê a configuração atual de uma conexão VPN (usado para pré-preencher o
    diálogo de edição). Nunca precisa de elevação, mesmo para conexões
    all-users — Get-VpnConnection só lê.

    Não existe cmdlet Get-VpnConnectionRoute neste módulo (só Add-/Remove-);
    as rotas de split tunneling vêm da propriedade Routes do próprio objeto
    retornado por Get-VpnConnection.

    Entrada (JSON): { name, all_users }
    Saída (JSON): { success, error, data: { server, tunnel_type, split_tunneling, routes: [] } }
#>
param(
    [Parameter(Mandatory = $true)][string]$InputJson,
    [Parameter(Mandatory = $true)][string]$OutputJson
)

$ErrorActionPreference = 'Stop'
$result = @{ success = $false; error = $null; data = $null }

try {
    $in = Get-Content -Raw -Path $InputJson | ConvertFrom-Json
    $allUsers = [bool]$in.all_users

    $conn = Get-VpnConnection -Name $in.name -AllUserConnection:$allUsers -ErrorAction Stop
    $routes = @()
    if ($conn.Routes) {
        $routes = @($conn.Routes | ForEach-Object { $_.DestinationPrefix })
    }

    $result.success = $true
    $result.data = @{
        server          = $conn.ServerAddress
        tunnel_type     = [string]$conn.TunnelType
        split_tunneling = [bool]$conn.SplitTunneling
        routes          = $routes
    }
} catch {
    $result.success = $false
    $result.error = $_.Exception.Message
}

$result | ConvertTo-Json -Depth 6 -Compress | Out-File -FilePath $OutputJson -Encoding utf8
if ($result.success) { exit 0 } else { exit 1 }
