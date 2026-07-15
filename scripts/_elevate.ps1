<#
    Wrapper não elevado que solicita UAC apenas para uma única operação.
    Nunca eleva o processo que o invoca (o VPN Manager continua rodando sem admin).
    Código de saída 1223 (ERROR_CANCELLED) sinaliza que o usuário recusou o UAC.
#>
param(
    [Parameter(Mandatory = $true)][string]$ScriptPath,
    [Parameter(Mandatory = $true)][string]$InputJson,
    [Parameter(Mandatory = $true)][string]$OutputJson
)

try {
    $proc = Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -PassThru `
        -WindowStyle Hidden `
        -ArgumentList @(
            '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', $ScriptPath, $InputJson, $OutputJson
        )
    exit $proc.ExitCode
} catch {
    exit 1223
}
