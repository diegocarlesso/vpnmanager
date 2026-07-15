<#
    Atualiza servidor/tipo de túnel/split-tunneling de uma conexão existente e
    reconcilia suas rotas. Nome e escopo (all_users) não são alteráveis aqui —
    identificam apenas qual conexão editar.
    Entrada (JSON): {
        name, all_users, server, tunnel_type, split_tunneling,
        routes_to_add: [], routes_to_remove: []
    }
    Quando split_tunneling = false, TODAS as rotas customizadas existentes são
    removidas (routes_to_add/routes_to_remove são ignoradas nesse caso), para
    não deixar rotas órfãs quando a conexão volta a usar rota padrão.
    Saída (JSON): { success, partial, error, data: { name, routes: [...] } }
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

    $conn = Set-VpnConnection -Name $in.name -ServerAddress $in.server -TunnelType $in.tunnel_type `
        -AllUserConnection:$allUsers -SplitTunneling:$splitTunneling -Force -Confirm:$false -PassThru -ErrorAction Stop

    $routeResults = @()
    $anyRouteFailed = $false

    if (-not $splitTunneling) {
        # Não existe Get-VpnConnectionRoute neste módulo: as rotas existentes vêm da
        # propriedade Routes do próprio Get-VpnConnection.
        $existingConn = Get-VpnConnection -Name $in.name -AllUserConnection:$allUsers -ErrorAction SilentlyContinue
        $existingRoutes = @()
        if ($existingConn -and $existingConn.Routes) {
            $existingRoutes = @($existingConn.Routes | ForEach-Object { $_.DestinationPrefix })
        }
        foreach ($r in $existingRoutes) {
            try {
                Remove-VpnConnectionRoute -ConnectionName $in.name -DestinationPrefix $r `
                    -AllUserConnection:$allUsers -Confirm:$false -ErrorAction Stop
                $routeResults += @{ route = $r; action = 'remove'; success = $true; error = $null }
            } catch {
                $anyRouteFailed = $true
                $routeResults += @{ route = $r; action = 'remove'; success = $false; error = $_.Exception.Message }
            }
        }
    } else {
        foreach ($route in @($in.routes_to_remove)) {
            try {
                Remove-VpnConnectionRoute -ConnectionName $in.name -DestinationPrefix $route `
                    -AllUserConnection:$allUsers -Confirm:$false -ErrorAction Stop
                $routeResults += @{ route = $route; action = 'remove'; success = $true; error = $null }
            } catch {
                $anyRouteFailed = $true
                $routeResults += @{ route = $route; action = 'remove'; success = $false; error = $_.Exception.Message }
            }
        }
        foreach ($route in @($in.routes_to_add)) {
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
