<#
  syswatch.ps1 — 0-token host collector for the dashboard System tab.

  Polls LibreHardwareMonitor (localhost:8085) + Windows perf counters + Defender,
  then POSTs a snapshot to the dashboard backend every few seconds. Runs on the
  Windows host (the dashboard backend lives in WSL/Docker and can't read these
  sensors directly). Install as a Scheduled Task at logon — see install note at bottom.

  Spends no tokens: pure local telemetry. The dashboard does spike detection.
#>
param(
  [string]$ConfigPath = "$PSScriptRoot\syswatch.config.json"
)

$ErrorActionPreference = 'Continue'
$cfg       = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$IngestUrl = $cfg.ingest_url
$LhmUrl    = $cfg.lhm_url
$Token     = $cfg.token
$Interval  = [int]$cfg.interval_sec
$ncores    = [Environment]::ProcessorCount

$GROUPS = 'Temperatures','Powers','Load','Clocks','Fans','Controls','Voltages','Data','Throughput'

# ---- state across loops ----
$prevCpu      = @{}             # pid -> total processor seconds
$prevTime     = $null
$signCache    = @{}            # path -> $true/$false/$null
$autorunBase  = @{}            # autorun-key -> $true (baseline; grows as new ones are acknowledged)
$def          = $null
$newAutoruns  = @()
$loop         = 0

function Walk-Lhm($node, $group, $acc) {
  if ($GROUPS -contains $node.Text) { $group = $node.Text }
  if ($node.Value) {
    $m = [regex]::Match([string]$node.Value, '-?[0-9]+(\.[0-9]+)?')
    if ($m.Success) { [void]$acc.Add([pscustomobject]@{ Group = $group; Name = $node.Text; Value = [double]$m.Value }) }
  }
  foreach ($c in $node.Children) { Walk-Lhm $c $group $acc }
}
function LV($acc, $group, $name) {
  ($acc | Where-Object { $_.Group -eq $group -and $_.Name -eq $name } | Select-Object -First 1).Value
}
function LMin($acc, $group, $like) {
  ($acc | Where-Object { $_.Group -eq $group -and $_.Name -like $like } | Measure-Object Value -Minimum).Minimum
}
function LMax($acc, $group, $like) {
  ($acc | Where-Object { $_.Group -eq $group -and $_.Name -like $like } | Measure-Object Value -Maximum).Maximum
}
function Is-Signed($path) {
  if (-not $path) { return $null }
  if ($signCache.ContainsKey($path)) { return $signCache[$path] }
  $res = $null
  try { $res = ((Get-AuthenticodeSignature $path -ErrorAction SilentlyContinue).Status -eq 'Valid') } catch { $res = $null }
  $signCache[$path] = $res
  return $res
}
function Get-Autoruns {
  $set = @{}
  $runKeys = @(
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run',
    'HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Run',
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
  )
  foreach ($k in $runKeys) {
    $p = Get-ItemProperty $k -ErrorAction SilentlyContinue
    if ($p) { $p.PSObject.Properties | Where-Object { $_.Name -notlike 'PS*' } | ForEach-Object { $set["$k\$($_.Name)=$($_.Value)"] = "$($_.Name) -> $($_.Value)" } }
  }
  foreach ($sf in @("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup",
                    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Startup")) {
    Get-ChildItem $sf -ErrorAction SilentlyContinue | ForEach-Object { $set["startup:$($_.FullName)"] = "$($_.Name) (startup folder)" }
  }
  return $set
}

Write-Host "syswatch -> $IngestUrl  (LHM $LhmUrl, every ${Interval}s, $ncores cores)"

while ($true) {
  $loop++
  try {
    $now = Get-Date

    # ---- LibreHardwareMonitor sensors ----
    $cpuTemp=$null; $cpuLoad=$null; $cpuPower=$null; $tjmin=$null; $warn=75; $crit=86
    $gpuTemp=$null; $gpuLoad=$null; $gpuFan=$null; $gpuHot=$null; $fans=@()
    try {
      $root = Invoke-RestMethod -Uri $LhmUrl -TimeoutSec 4
      $acc  = New-Object System.Collections.ArrayList
      foreach ($hw in $root.Children) { Walk-Lhm $hw $null $acc }
      $cpuTemp  = LV  $acc 'Temperatures' 'CPU Package'
      if ($null -eq $cpuTemp) { $cpuTemp = LMax $acc 'Temperatures' 'CPU Core #*' }
      $cpuPower = LV  $acc 'Powers'       'CPU Package'
      $cpuLoad  = LV  $acc 'Load'         'CPU Total'
      $tjmin    = LMin $acc 'Temperatures' 'CPU Core #* Distance to TjMax'
      $gpuTemp  = LV  $acc 'Temperatures' 'GPU Core'
      $gpuHot   = LV  $acc 'Temperatures' 'GPU Hot Spot'
      $gpuLoad  = LV  $acc 'Load'         'GPU Core'
      $fans = @($acc | Where-Object { $_.Group -eq 'Fans' } | ForEach-Object { @{ name = $_.Name; rpm = [int]$_.Value } })
      $gf = $acc | Where-Object { $_.Group -eq 'Fans' -and $_.Name -like '*GPU*' } | Select-Object -First 1
      if ($gf) { $gpuFan = [int]$gf.Value } elseif ($fans.Count -gt 0) { $gpuFan = $fans[0].rpm }
    } catch { Write-Host "LHM fetch failed: $($_.Exception.Message)" }

    # ---- per-process CPU (delta) + GPU + signing ----
    $procs = Get-Process -ErrorAction SilentlyContinue
    $elapsed = if ($prevTime) { ($now - $prevTime).TotalSeconds } else { $Interval }
    if ($elapsed -le 0) { $elapsed = $Interval }
    $gpuByPid = @{}
    try {
      (Get-Counter '\GPU Engine(*)\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples |
        Where-Object { $_.CookedValue -gt 0 -and $_.InstanceName -match 'pid_(\d+)_' } |
        ForEach-Object { $pid2 = [int]$matches[1]; $gpuByPid[$pid2] = [double]$gpuByPid[$pid2] + $_.CookedValue }
    } catch {}

    # per-process external network activity (established conns to a non-local remote)
    $netByPid = @{}
    try {
      Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | ForEach-Object {
        $ra = [string]$_.RemoteAddress
        if ($ra -and $ra -ne '127.0.0.1' -and $ra -ne '::1' -and $ra -ne '0.0.0.0' -and -not $ra.StartsWith('::ffff:127.')) {
          $op = [int]$_.OwningProcess; $netByPid[$op] = [int]$netByPid[$op] + 1
        }
      }
    } catch {}

    $rows = @()
    foreach ($p in $procs) {
      $cpuSec = $null; try { $cpuSec = $p.CPU } catch {}
      $pct = $null
      if ($null -ne $cpuSec -and $prevCpu.ContainsKey($p.Id)) {
        $d = $cpuSec - $prevCpu[$p.Id]; if ($d -lt 0) { $d = 0 }
        $pct = [math]::Round(($d / $elapsed / $ncores) * 100, 1)
      }
      $path = $null; try { $path = $p.Path } catch {}
      $rows += [pscustomobject]@{
        name = $p.ProcessName; pid = $p.Id; cpu = $pct;
        gpu = if ($gpuByPid.ContainsKey($p.Id)) { [math]::Round([math]::Min($gpuByPid[$p.Id],100),1) } else { $null };
        net_conns = if ($netByPid.ContainsKey($p.Id)) { $netByPid[$p.Id] } else { 0 };
        signed = (Is-Signed $path); path = $path
      }
    }
    # refresh prev cpu table
    $prevCpu = @{}; foreach ($p in $procs) { try { if ($null -ne $p.CPU) { $prevCpu[$p.Id] = $p.CPU } } catch {} }
    $prevTime = $now

    $top = @($rows | Sort-Object { if ($null -eq $_.cpu) { -1 } else { $_.cpu } } -Descending | Select-Object -First 10)

    # ---- memory + disk ----
    $memPct = $null; $diskBusy = $null
    try { $os = Get-CimInstance Win32_OperatingSystem; $memPct = [math]::Round((1 - ($os.FreePhysicalMemory / $os.TotalVisibleMemorySize)) * 100, 0) } catch {}
    try { $diskBusy = [math]::Round([math]::Min(((Get-Counter '\PhysicalDisk(_Total)\% Disk Time' -ErrorAction SilentlyContinue).CounterSamples[0].CookedValue), 100), 0) } catch {}

    # ---- security (slow cadence) ----
    if ($loop -eq 1 -or ($loop % 10) -eq 0) {
      try {
        $d = Get-MpComputerStatus -ErrorAction SilentlyContinue
        $lt = $null
        try { $t = Get-MpThreatDetection -ErrorAction SilentlyContinue | Sort-Object InitialDetectionTime -Descending | Select-Object -First 1; if ($t) { $lt = "$($t.ThreatID)" } } catch {}
        $def = @{ rtp = [bool]$d.RealTimeProtectionEnabled; engine_ok = [bool]$d.AMServiceEnabled; last_threat = $lt }
      } catch {}
      try {
        $cur = Get-Autoruns
        if ($autorunBase.Count -eq 0) { $autorunBase = $cur; $newAutoruns = @() }
        else {
          $fresh = @()
          foreach ($k in $cur.Keys) { if (-not $autorunBase.ContainsKey($k)) { $fresh += @{ name = $cur[$k]; path = $k }; $autorunBase[$k] = $true } }
          $newAutoruns = $fresh
        }
      } catch {}
    }

    # ---- suspicious flags: scan ALL procs (not just CPU-top) for
    #      unsigned + (network-active OR high-resource) — the real triad ----
    $flags = @()
    foreach ($tp in $rows) {
      if ($tp.signed -ne $false) { continue }   # only unsigned binaries are candidates
      $netActive = ($tp.net_conns -gt 0)
      if ($netActive -or ($tp.cpu -ge 25) -or ($tp.gpu -ge 40)) {
        $why = @()
        if ($netActive)      { $why += "$($tp.net_conns) external conn(s)" }
        if ($tp.cpu -ge 25)  { $why += "$($tp.cpu)% cpu" }
        if ($tp.gpu -ge 40)  { $why += "$($tp.gpu)% gpu" }
        $flags += @{ proc = $tp.name; pid = $tp.pid; why = "unsigned + " + ($why -join ', ') }
      }
    }
    $flags = @($flags | Select-Object -First 8)

    # ---- ship it ----
    $payload = @{
      ts  = $now.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
      cpu = @{ temp = $cpuTemp; load = $cpuLoad; power_w = $cpuPower; tjmax_distance = $tjmin; warn = $warn; crit = $crit }
      gpu = @{ temp = $gpuTemp; load = $gpuLoad; fan_rpm = $gpuFan; hotspot = $gpuHot }
      mem = @{ used_pct = $memPct }
      disk = @{ busy_pct = $diskBusy }
      fans = $fans
      top = $top
      security = @{ defender = $def; flags = $flags; new_autoruns = $newAutoruns }
    } | ConvertTo-Json -Depth 6

    try {
      Invoke-RestMethod -Uri $IngestUrl -Method Post -Body $payload -ContentType 'application/json' `
        -Headers @{ 'X-System-Token' = $Token } -TimeoutSec 8 | Out-Null
    } catch { Write-Host "ingest POST failed: $($_.Exception.Message)" }
  }
  catch { Write-Host "loop error: $($_.Exception.Message)" }

  Start-Sleep -Seconds $Interval
}
