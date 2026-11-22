<#
Despliegue de la VM del verificador (fase 3). PowerShell, desde la raíz del repositorio.

Sin -Aplicar solo imprime los comandos (no crea ni cambia nada). Con -Aplicar:
  1. Reglas de firewall de la VPC para la etiqueta `cyc-verificador`: nada entra salvo SSH por IAP;
     solo sale tráfico al 443.
  2. VM e2-standard-2 Spot, Debian 12, SIN cuenta de servicio ni scopes, Shielded VM, 30 GB.
     Metadatos: URL de la API y el token de la cola (lo único sensible de la VM).
  3. Copia del código (git archive de verifier/) por IAP a /opt/cyc. No se clona el repositorio:
     la VM no tiene credenciales de GitHub. Antes, actualiza el script de arranque de la instancia y
     la enciende (se apaga sola tras 15 min sin trabajo).

Con -Arranque (aparte): rol personalizado `cycVerificadorArranque` (solo compute.instances.get y
compute.instances.start) otorgado a la cuenta de servicio de la API SOLO sobre esta VM, para que la
API la encienda cuando hay trabajo (backend/ejecucion/arranque.py). No puede detenerla ni cambiarla.

El token de la cola se lee de Secret Manager desde ESTA máquina (tu gcloud), nunca se imprime y
viaja a la VM solo como metadato de la instancia.

Uso:
  ./verifier/deploy/deploy.ps1 -ApiUrl https://cumpleycobra-api-staging-....run.app            # muestra
  ./verifier/deploy/deploy.ps1 -ApiUrl https://... -Aplicar                                    # crea
  ./verifier/deploy/deploy.ps1 -SoloCodigo -Aplicar                                            # actualiza el código
  ./verifier/deploy/deploy.ps1 -Arranque -CuentaApi cyc-api@PROYECTO.iam.gserviceaccount.com -Aplicar
#>
param(
    [string]$ApiUrl = "",
    [string]$Zona = "us-central1-a",
    [string]$Vm = "cyc-verificador",
    [string]$SecretoToken = "cyc-verifier-queue-token",
    [switch]$SoloCodigo,
    [switch]$Arranque,
    [string]$CuentaApi = "",
    [string]$Rol = "cycVerificadorArranque",
    [switch]$Aplicar
)
# "Continue": en Windows PowerShell 5.1 la salida de progreso de gcloud (stderr) se tomaría como error.
# Cada paso se juzga por su código de salida.
$ErrorActionPreference = "Continue"

function Paso([string]$texto, [string[]]$comando) {
    Write-Host "`n# $texto"
    Write-Host ("gcloud " + ($comando -join " "))
    if ($Aplicar) {
        & gcloud @comando
        if ($LASTEXITCODE -ne 0) { throw "falló: $texto" }
    }
}

if ($Arranque) {
    if (-not $CuentaApi) { throw "Falta -CuentaApi (la cuenta de servicio de Cloud Run)" }
    $proyecto = (& gcloud config get-value project 2>$null | Out-String).Trim()
    Paso "Rol mínimo para encender la VM (leer su estado y encenderla; nada más)" @(
        "iam", "roles", "create", $Rol, "--project=$proyecto", "--title=Encender el verificador de Cumple&Cobra",
        "--permissions=compute.instances.get,compute.instances.start", "--stage=GA")
    Paso "Ese rol, solo sobre la VM del verificador, para la cuenta de la API" @(
        "compute", "instances", "add-iam-policy-binding", $Vm, "--zone=$Zona",
        "--member=serviceAccount:$CuentaApi", "--role=projects/$proyecto/roles/$Rol")
    if (-not $Aplicar) { Write-Host "`nNo se aplicó nada: vuelve a correrlo con -Aplicar." }
    return
}

if (-not $SoloCodigo) {
    if (-not $ApiUrl) { throw "Falta -ApiUrl (la URL de la API que atiende la cola)" }

    Paso "Firewall: SSH solo desde IAP" @(
        "compute", "firewall-rules", "create", "cyc-verificador-iap-ssh", "--network=default", "--direction=INGRESS",
        "--action=ALLOW", "--rules=tcp:22", "--source-ranges=35.235.240.0/20", "--target-tags=cyc-verificador", "--priority=1000")
    Paso "Firewall: ninguna otra entrada" @(
        "compute", "firewall-rules", "create", "cyc-verificador-deny-ingress", "--network=default", "--direction=INGRESS",
        "--action=DENY", "--rules=all", "--source-ranges=0.0.0.0/0", "--target-tags=cyc-verificador", "--priority=2000")
    Paso "Firewall: salida solo al 443" @(
        "compute", "firewall-rules", "create", "cyc-verificador-allow-443", "--network=default", "--direction=EGRESS",
        "--action=ALLOW", "--rules=tcp:443", "--destination-ranges=0.0.0.0/0", "--target-tags=cyc-verificador", "--priority=1000")
    Paso "Firewall: ninguna otra salida (el DNS y la hora van al servidor de metadatos, que no pasa por el firewall)" @(
        "compute", "firewall-rules", "create", "cyc-verificador-deny-egress", "--network=default", "--direction=EGRESS",
        "--action=DENY", "--rules=all", "--destination-ranges=0.0.0.0/0", "--target-tags=cyc-verificador", "--priority=2000")

    Write-Host "`n# Token de la cola: se lee de Secret Manager ($SecretoToken) y no se imprime"
    $token = ""
    if ($Aplicar) {
        $token = (& gcloud secrets versions access latest --secret=$SecretoToken 2>$null | Out-String).Trim()
        if (-not $token) { throw "El secreto $SecretoToken está vacío" }
    }
    $metadata = "verifier-api-url=$ApiUrl,verifier-queue-token=" + ($(if ($Aplicar) { $token } else { "<token>" }))
    $crear = @(
        "compute", "instances", "create", $Vm, "--zone=$Zona", "--machine-type=e2-standard-2",
        "--provisioning-model=SPOT", "--instance-termination-action=STOP",
        "--no-service-account", "--no-scopes",
        "--image-family=debian-12", "--image-project=debian-cloud", "--boot-disk-size=30GB",
        "--shielded-secure-boot", "--shielded-vtpm", "--shielded-integrity-monitoring",
        "--tags=cyc-verificador", "--metadata-from-file=startup-script=verifier/deploy/startup.sh",
        "--metadata=$metadata")
    Write-Host "`n# VM Spot sin cuenta de servicio"
    Write-Host ("gcloud " + (($crear -join " ") -replace "verifier-queue-token=[^,\s]+", "verifier-queue-token=<token>"))
    if ($Aplicar) {
        & gcloud @crear
        if ($LASTEXITCODE -ne 0) { throw "falló la creación de la VM" }
    }
    $token = $null
}

# --- Código: git archive de verifier/ por IAP ------------------------------------------------
if ($SoloCodigo) {
    Paso "Script de arranque de la instancia (corre en cada encendido)" @(
        "compute", "instances", "add-metadata", $Vm, "--zone=$Zona", "--metadata-from-file=startup-script=verifier/deploy/startup.sh")
    Paso "Encender la VM para copiar el código (se apaga sola tras 15 min sin trabajo)" @(
        "compute", "instances", "start", $Vm, "--zone=$Zona")
}
$tar = Join-Path $env:TEMP "cyc-verifier.tar"
Write-Host "`n# Código del verificador (git archive HEAD verifier/) por IAP a /opt/cyc"
Write-Host "git archive --format=tar -o $tar HEAD verifier"
Write-Host "gcloud compute scp $tar ${Vm}:/tmp/cyc-verifier.tar --zone=$Zona --tunnel-through-iap --strict-host-key-checking=no"
Write-Host "gcloud compute ssh $Vm --zone=$Zona --tunnel-through-iap --strict-host-key-checking=no --command=`"sudo mkdir -p /opt/cyc && sudo tar -xf /tmp/cyc-verifier.tar -C /opt/cyc && sudo systemctl restart google-startup-scripts`""
if ($Aplicar) {
    git archive --format=tar -o $tar HEAD verifier
    if ($LASTEXITCODE -ne 0) { throw "falló git archive" }
    & gcloud compute scp $tar "${Vm}:/tmp/cyc-verifier.tar" --zone=$Zona --tunnel-through-iap --strict-host-key-checking=no
    if ($LASTEXITCODE -ne 0) { throw "falló la copia por IAP" }
    & gcloud compute ssh $Vm --zone=$Zona --tunnel-through-iap --strict-host-key-checking=no --command="sudo mkdir -p /opt/cyc && sudo tar -xf /tmp/cyc-verifier.tar -C /opt/cyc && sudo systemctl restart google-startup-scripts"
    if ($LASTEXITCODE -ne 0) { throw "falló la instalación del código" }
    Remove-Item $tar
}
if (-not $Aplicar) { Write-Host "`nNo se aplicó nada: vuelve a correrlo con -Aplicar." }
