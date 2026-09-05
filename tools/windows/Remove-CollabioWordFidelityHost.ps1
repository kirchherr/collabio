[CmdletBinding()]
param(
    [ValidateSet("Audit", "Apply")]
    [string]$Mode = "Audit",

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^S-1-5-21-(?:[0-9]+-){3}[0-9]+$")]
    [string]$ExpectedRunnerSid,

    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,19}$")]
    [string]$RunnerAccount = "collabio-word-runner",
    [string]$WorkspaceRoot = "C:\ProgramData\Collabio\WordFidelity",
    [string]$SigningCustodyPath = "C:\Users\tkirchherr\.collabio\signing",
    [switch]$LogoffRunnerSession,
    [switch]$RemoveRunnerProfile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PurposeDescription = "Collabio Word fidelity interactive runner"
$FirewallRuleName = "Collabio Word fidelity outbound deny"
$ExpectedWorkspaceRoot = "C:\ProgramData\Collabio\WordFidelity"
$ExpectedSigningCustodyPath = "C:\Users\tkirchherr\.collabio\signing"
$ExpectedProfilePath = "C:\Users\collabio-word-runner"
$UsersSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-545")
$RunnerSid = [Security.Principal.SecurityIdentifier]::new($ExpectedRunnerSid)
$AllowedWorkspaceEntries = @("assignments", "handoffs", "reports", "Invoke-CollabioWordFidelity.ps1")

function Get-Sha256Bytes {
    param([byte[]]$Content)

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return "sha256:" + ([BitConverter]::ToString($sha.ComputeHash($Content))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-Sha256String {
    param([string]$Value)

    return Get-Sha256Bytes -Content ([Text.UTF8Encoding]::new($false).GetBytes($Value))
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-NewJsonPath {
    param([string]$Path)

    $fullPath = [IO.Path]::GetFullPath($Path)
    if ([IO.File]::Exists($fullPath) -or [IO.Directory]::Exists($fullPath)) {
        throw "The decommission report path must not already exist."
    }
    $parent = [IO.Path]::GetDirectoryName($fullPath)
    if (-not $parent -or -not [IO.Directory]::Exists($parent)) {
        throw "The decommission report parent directory must already exist."
    }
    $parentItem = Get-Item -LiteralPath $parent -Force
    if ($parentItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "The decommission report parent directory must not be a reparse point."
    }
}

function Write-NewJson {
    param([string]$Path, $Value)

    Assert-NewJsonPath -Path $Path
    $fullPath = [IO.Path]::GetFullPath($Path)
    $json = (ConvertTo-Json -InputObject $Value -Depth 8) + "`n"
    $stream = [IO.File]::Open($fullPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally {
        $stream.Dispose()
    }
}

function Assert-ExactLocalPath {
    param([string]$Path, [string]$ExpectedPath, [string]$Label)

    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd("\")
    $expectedFullPath = [IO.Path]::GetFullPath($ExpectedPath).TrimEnd("\")
    if (-not $fullPath.Equals($expectedFullPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label must resolve exactly to $expectedFullPath."
    }
    $root = [IO.Path]::GetPathRoot($fullPath)
    if (-not $root -or [IO.DriveInfo]::new($root).DriveType -ne [IO.DriveType]::Fixed) {
        throw "$Label must be on a local fixed drive."
    }
    return $fullPath
}

function Get-WordExecutable {
    $candidates = @(
        (Join-Path ${env:ProgramFiles} "Microsoft Office\root\Office16\WINWORD.EXE"),
        (Join-Path ${env:ProgramFiles(x86)} "Microsoft Office\root\Office16\WINWORD.EXE"),
        (Join-Path ${env:ProgramFiles} "Microsoft Office\Office16\WINWORD.EXE"),
        (Join-Path ${env:ProgramFiles(x86)} "Microsoft Office\Office16\WINWORD.EXE")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $item = Get-Item -LiteralPath $candidate -Force
            if (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                return $item.FullName
            }
        }
    }
    return $null
}

function Get-RunnerAccount {
    $account = Get-LocalUser -Name $RunnerAccount -ErrorAction SilentlyContinue
    if ($account -and $account.SID.Value -ne $RunnerSid.Value) {
        throw "The runner account SID does not match ExpectedRunnerSid."
    }
    if ($account -and $account.Description -ne $PurposeDescription) {
        throw "The runner account purpose does not match the Collabio fidelity purpose."
    }
    return $account
}

function Get-MembershipSids {
    $memberships = [Collections.Generic.List[string]]::new()
    foreach ($group in @(Get-LocalGroup)) {
        $members = @(Get-LocalGroupMember -Group $group.Name -ErrorAction Stop)
        if (@($members | Where-Object { $_.SID -and $_.SID.Value -eq $RunnerSid.Value }).Count -gt 0) {
            $memberships.Add([string]$group.SID.Value)
        }
    }
    return @($memberships | Sort-Object -Unique)
}

function Get-SigningEntries {
    param($Acl)

    $entries = [Collections.Generic.List[object]]::new()
    foreach ($entry in @($Acl.Access)) {
        try {
            $entrySid = $entry.IdentityReference.Translate([Security.Principal.SecurityIdentifier])
        }
        catch {
            continue
        }
        if ($entrySid.Value -eq $RunnerSid.Value) {
            $entries.Add($entry)
        }
    }
    return @($entries)
}

function Get-FirewallState {
    $rules = @(Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue)
    if ($rules.Count -gt 1) {
        throw "More than one firewall rule uses the Collabio fidelity rule name."
    }
    if ($rules.Count -eq 0) {
        return [ordered]@{ present = $false; verified = $true; rule = $null }
    }

    $wordPath = Get-WordExecutable
    if (-not $wordPath) {
        throw "WINWORD.EXE cannot be measured while the fidelity firewall rule still exists."
    }
    $rule = $rules[0]
    $applications = @($rule | Get-NetFirewallApplicationFilter -ErrorAction Stop)
    $addresses = @($rule | Get-NetFirewallAddressFilter -ErrorAction Stop)
    $ports = @($rule | Get-NetFirewallPortFilter -ErrorAction Stop)
    $verified = (
        $rule.Direction.ToString() -eq "Outbound" -and
        $rule.Action.ToString() -eq "Block" -and
        $rule.Enabled.ToString() -eq "True" -and
        $rule.Profile.ToString() -eq "Any" -and
        $applications.Count -eq 1 -and
        [string]$applications[0].Program -eq $wordPath -and
        $addresses.Count -eq 1 -and
        [string]$addresses[0].RemoteAddress -eq "Any" -and
        $ports.Count -eq 1 -and
        [string]$ports[0].Protocol -eq "Any"
    )
    if (-not $verified) {
        throw "The named fidelity firewall rule drifted; refusing removal."
    }
    return [ordered]@{ present = $true; verified = $true; rule = $rule }
}

function Assert-WorkspaceBoundary {
    param([string]$FullPath)

    if (-not (Test-Path -LiteralPath $FullPath)) {
        return $false
    }
    if (-not (Test-Path -LiteralPath $FullPath -PathType Container)) {
        throw "The fidelity workspace path is not a directory."
    }
    $rootItem = Get-Item -LiteralPath $FullPath -Force
    if ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "The fidelity workspace root must not be a reparse point."
    }
    foreach ($entry in @(Get-ChildItem -LiteralPath $FullPath -Force)) {
        if ($AllowedWorkspaceEntries -notcontains $entry.Name) {
            throw "The fidelity workspace contains an unexpected top-level entry."
        }
    }
    foreach ($entry in @(Get-ChildItem -LiteralPath $FullPath -Force -Recurse)) {
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "The fidelity workspace tree must not contain reparse points."
        }
    }
    return $true
}

function Get-RunnerProfiles {
    $profiles = @(Get-CimInstance Win32_UserProfile | Where-Object { $_.SID -eq $RunnerSid.Value })
    if ($profiles.Count -gt 1) {
        throw "More than one Windows profile matches the runner SID."
    }
    foreach ($profile in $profiles) {
        $profilePath = [IO.Path]::GetFullPath([string]$profile.LocalPath).TrimEnd("\")
        $expectedPath = [IO.Path]::GetFullPath($ExpectedProfilePath).TrimEnd("\")
        if (-not $profilePath.Equals($expectedPath, [StringComparison]::OrdinalIgnoreCase) -or $profile.Special) {
            throw "The runner SID is bound to an unexpected Windows profile."
        }
    }
    return $profiles
}

function Get-RunnerSessionIds {
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $lines = @(& "$env:SystemRoot\System32\quser.exe" 2>$null)
        $queryExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($queryExitCode -ne 0) {
        return @()
    }
    $ids = [Collections.Generic.List[int]]::new()
    foreach ($line in $lines) {
        $tokens = @(([string]$line).Trim().TrimStart(">").Split(
                @(" ", "`t"), [StringSplitOptions]::RemoveEmptyEntries
            ))
        if ($tokens.Count -lt 2 -or $tokens[0] -ne $RunnerAccount) {
            continue
        }
        foreach ($token in $tokens[1..($tokens.Count - 1)]) {
            if ($token -match "^[0-9]+$") {
                $ids.Add([int]$token)
                break
            }
        }
    }
    return @($ids | Sort-Object -Unique)
}

$workspaceFull = Assert-ExactLocalPath -Path $WorkspaceRoot -ExpectedPath $ExpectedWorkspaceRoot `
    -Label "Fidelity workspace"
$signingFull = Assert-ExactLocalPath -Path $SigningCustodyPath -ExpectedPath $ExpectedSigningCustodyPath `
    -Label "Signing custody"
Assert-NewJsonPath -Path $OutputPath

if (-not (Test-Path -LiteralPath $signingFull -PathType Container)) {
    throw "Signing custody must remain present during decommissioning."
}
$signingItem = Get-Item -LiteralPath $signingFull -Force
if ($signingItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw "Signing custody must not be a reparse point."
}

$account = Get-RunnerAccount
$memberships = @()
if ($account) {
    $memberships = @(Get-MembershipSids)
}
if ($account -and ($memberships.Count -ne 1 -or $memberships[0] -ne $UsersSid.Value)) {
    throw "The runner account has unexpected local group membership."
}

$signingAcl = Get-Acl -LiteralPath $signingFull
$signingEntries = @(Get-SigningEntries -Acl $signingAcl)
foreach ($entry in $signingEntries) {
    if ($entry.IsInherited -or $entry.AccessControlType -ne [Security.AccessControl.AccessControlType]::Deny -or
        $entry.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl) {
        throw "The runner signing-custody rule drifted; refusing removal."
    }
}
if ($signingEntries.Count -gt 1) {
    throw "More than one explicit runner rule exists on signing custody."
}

$firewall = Get-FirewallState
$workspacePresent = Assert-WorkspaceBoundary -FullPath $workspaceFull
$profiles = @(Get-RunnerProfiles)
$sessions = @(Get-RunnerSessionIds)
$wordProcesses = @(Get-Process -Name WINWORD -ErrorAction SilentlyContinue)
if ($wordProcesses.Count -gt 0) {
    throw "WINWORD.EXE is running; refusing fidelity-host decommissioning."
}

$removed = [ordered]@{
    account = $false
    firewall_rule = $false
    signing_acl_rule = $false
    workspace = $false
    runner_profile = $false
    runner_sessions = 0
}

if ($Mode -eq "Apply") {
    if (-not (Test-IsAdministrator)) {
        throw "Apply mode requires an elevated Windows PowerShell session."
    }
    if ($sessions.Count -gt 0 -and -not $LogoffRunnerSession) {
        throw "Runner sessions exist; use -LogoffRunnerSession after review."
    }
    if ($profiles.Count -gt 0 -and -not $RemoveRunnerProfile) {
        throw "A runner profile exists; use -RemoveRunnerProfile after review."
    }

    if ($account -and $account.Enabled) {
        Disable-LocalUser -Name $RunnerAccount -Confirm:$false
    }
    foreach ($sessionId in $sessions) {
        & "$env:SystemRoot\System32\logoff.exe" $sessionId
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to log off a reviewed runner session."
        }
        $removed.runner_sessions += 1
    }
    if ($sessions.Count -gt 0) {
        for ($attempt = 0; $attempt -lt 30; $attempt += 1) {
            Start-Sleep -Seconds 1
            $profiles = @(Get-RunnerProfiles)
            if (@($profiles | Where-Object { $_.Loaded }).Count -eq 0) {
                break
            }
        }
    }
    if (@($profiles | Where-Object { $_.Loaded }).Count -gt 0) {
        throw "The runner profile remained loaded after session logoff."
    }

    if ($signingEntries.Count -eq 1) {
        $signingAcl.PurgeAccessRules($RunnerSid)
        Set-Acl -LiteralPath $signingFull -AclObject $signingAcl
        $removed.signing_acl_rule = $true
    }
    if ($firewall.present) {
        $firewall.rule | Remove-NetFirewallRule -Confirm:$false
        $removed.firewall_rule = $true
    }
    if ($workspacePresent) {
        $verifiedWorkspace = Assert-ExactLocalPath -Path $workspaceFull -ExpectedPath $ExpectedWorkspaceRoot `
            -Label "Fidelity workspace"
        [void](Assert-WorkspaceBoundary -FullPath $verifiedWorkspace)
        Remove-Item -LiteralPath $verifiedWorkspace -Recurse -Force
        $removed.workspace = $true
    }
    if ($profiles.Count -eq 1) {
        $profiles[0] | Remove-CimInstance -Confirm:$false
        $removed.runner_profile = $true
    }
    if ($account) {
        Remove-LocalUser -Name $RunnerAccount -Confirm:$false
        $removed.account = $true
    }
}

$postAccount = Get-LocalUser -Name $RunnerAccount -ErrorAction SilentlyContinue
$postFirewall = @(Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue)
$postSigningAcl = Get-Acl -LiteralPath $signingFull
$postSigningEntries = @(Get-SigningEntries -Acl $postSigningAcl)
$postProfiles = @(Get-RunnerProfiles)
$postWorkspacePresent = Test-Path -LiteralPath $workspaceFull
$postSessions = @(Get-RunnerSessionIds)
$decommissioned = (
    -not $postAccount -and
    $postFirewall.Count -eq 0 -and
    $postSigningEntries.Count -eq 0 -and
    $postProfiles.Count -eq 0 -and
    -not $postWorkspacePresent -and
    $postSessions.Count -eq 0
)

$report = [ordered]@{
    schema_version = "genoffice_docx_word_host_decommission_report.v1"
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    mode = $Mode.ToLowerInvariant()
    decommissioned = $decommissioned
    runner_account_present = [bool]$postAccount
    runner_session_count = $postSessions.Count
    runner_profile_count = $postProfiles.Count
    firewall_rule_count = $postFirewall.Count
    signing_acl_rule_count = $postSigningEntries.Count
    workspace_present = [bool]$postWorkspacePresent
    removed = $removed
    runner_sid_sha256 = Get-Sha256String -Value $RunnerSid.Value
    workspace_path_sha256 = Get-Sha256String -Value $workspaceFull
    signing_custody_path_sha256 = Get-Sha256String -Value $signingFull
    signing_custody_contents_accessed = $false
    tenant_content_included = $false
    private_key_included = $false
}
Write-NewJson -Path $OutputPath -Value $report

if ($Mode -eq "Apply" -and -not $decommissioned) {
    exit 2
}
