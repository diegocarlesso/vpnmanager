<#
    Cria uma nova conexão VPN e, se split tunneling estiver ativo, suas rotas.
    Entrada (JSON): { name, server, tunnel_type, l2tp_psk, all_users, split_tunneling, routes: [] }
    Saída (JSON): { success, partial, error, data: { name, routes: [{route, action, success, error}] } }
#>
param(
    [Parameter(Mandatory = $true)][string]$InputJson,
    [Parameter(Mandatory = $true)][string]$OutputJson
)

$ErrorActionPreference = 'Stop'
$result = @{ success = $false; partial = $false; error = $null; data = $null }

try {
    $in = Get-Content -Raw -Path $InputJson | ConvertFrom-Json
    $allUsers = [bool]$in.all_users
    $splitTunneling = [bool]$in.split_tunneling

    $vpnParams = @{
        Name              = $in.name
        ServerAddress     = $in.server
        TunnelType        = $in.tunnel_type
        AllUserConnection = $allUsers
        SplitTunneling    = $splitTunneling
        Force             = $true
        PassThru          = $true
        ErrorAction       = 'Stop'
    }
    if ([string]::Equals([string]$in.tunnel_type, 'L2tp', [System.StringComparison]::OrdinalIgnoreCase) -and
        -not [string]::IsNullOrWhiteSpace([string]$in.l2tp_psk)) {
        $vpnParams['L2tpPsk'] = [string]$in.l2tp_psk
    }

    $conn = Add-VpnConnection @vpnParams

    $routeResults = @()
    $anyRouteFailed = $false
    if ($splitTunneling) {
        foreach ($route in @($in.routes)) {
            try {
                Add-VpnConnectionRoute -ConnectionName $in.name -DestinationPrefix $route `
                    -AllUserConnection:$allUsers -PassThru -Confirm:$false -ErrorAction Stop | Out-Null
                $routeResults += @{ route = $route; action = 'add'; success = $true; error = $null }
            } catch {
                $anyRouteFailed = $true
                $routeResults += @{ route = $route; action = 'add'; success = $false; error = $_.Exception.Message }
            }
        }
    }

    $result.success = $true
    $result.partial = $anyRouteFailed
    $result.data = @{ name = $conn.Name; routes = $routeResults }
} catch {
    $result.success = $false
    $result.error = $_.Exception.Message
}

$result | ConvertTo-Json -Depth 6 -Compress | Out-File -FilePath $OutputJson -Encoding utf8
if ($result.success) { exit 0 } else { exit 1 }
