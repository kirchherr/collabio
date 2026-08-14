[CmdletBinding()]
param(
    [ValidateSet("Audit", "Apply")]
    [string]$Mode = "Audit",

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,19}$")]
    [string]$RunnerAccount = "collabio-word-runner",
    [string]$WorkspaceRoot = "C:\ProgramData\Collabio\WordFidelity",
    [string]$SigningCustodyPath = "C:\Users\tkirchherr\.collabio\signing",
    [switch]$AdoptExistingAccount,
    [switch]$RotatePassword,
    [switch]$ReplaceDriftedFirewallRule
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ZeroHash = "sha256:" + ("0" * 64)
$PurposeDescription = "Collabio Word fidelity interactive runner"
$FirewallRuleName = "Collabio Word fidelity outbound deny"
$UsersSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-545")
$AdministratorsSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")
$SystemSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-18")
$WorkspaceDirectories = @("assignments", "handoffs", "reports")

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

function Get-Sha256File {
    param([string]$Path)

    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "A measured executable or script is not a regular file."
    }
    $stream = [IO.File]::Open($item.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return "sha256:" + ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function Assert-NewJsonPath {
    param([string]$Path)

    $fullPath = [IO.Path]::GetFullPath($Path)
    if ([IO.File]::Exists($fullPath) -or [IO.Directory]::Exists($fullPath)) {
        throw "The bootstrap report path must not already exist."
    }
    $parent = [IO.Path]::GetDirectoryName($fullPath)
    if (-not $parent -or -not [IO.Directory]::Exists($parent)) {
        throw "The bootstrap report parent directory must already exist."
    }
    $parentItem = Get-Item -LiteralPath $parent -Force
    if ($parentItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "The bootstrap report parent directory must not be a reparse point."
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

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-LocalFixedPath {
    param([string]$Path, [string]$Label)

    $fullPath = [IO.Path]::GetFullPath($Path)
    if ($fullPath.StartsWith("\\", [StringComparison]::Ordinal)) {
        throw "$Label must be on a local fixed drive."
    }
    $root = [IO.Path]::GetPathRoot($fullPath)
    if (-not $root -or [IO.DriveInfo]::new($root).DriveType -ne [IO.DriveType]::Fixed) {
        throw "$Label must be on a local fixed drive."
    }
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

function Read-ConfirmedPassword {
    $first = Read-Host "Enter the dedicated local runner password" -AsSecureString
    $second = Read-Host "Confirm the dedicated local runner password" -AsSecureString
    $firstBstr = [IntPtr]::Zero
    $secondBstr = [IntPtr]::Zero
    try {
        $firstBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($first)
        $secondBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($second)
        $firstLength = [Runtime.InteropServices.Marshal]::ReadInt32($firstBstr, -4)
        $secondLength = [Runtime.InteropServices.Marshal]::ReadInt32($secondBstr, -4)
        if ($firstLength -eq 0 -or $firstLength -ne $secondLength) {
            throw "The password confirmation did not match."
        }
        for ($offset = 0; $offset -lt $firstLength; $offset += 2) {
            if ([Runtime.InteropServices.Marshal]::ReadInt16($firstBstr, $offset) -ne
                [Runtime.InteropServices.Marshal]::ReadInt16($secondBstr, $offset)) {
                throw "The password confirmation did not match."
            }
        }
        return $first
    }
    catch {
        $first.Dispose()
        throw
    }
    finally {
        $second.Dispose()
        if ($firstBstr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($firstBstr)
        }
        if ($secondBstr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secondBstr)
        }
    }
}

function Get-MembershipSids {
    param([Security.Principal.SecurityIdentifier]$AccountSid)

    $memberships = [Collections.Generic.List[string]]::new()
    foreach ($group in @(Get-LocalGroup)) {
        $members = @(Get-LocalGroupMember -Group $group.Name -ErrorAction Stop)
        if (@($members | Where-Object { $_.SID -and $_.SID.Value -eq $AccountSid.Value }).Count -gt 0) {
            $memberships.Add([string]$group.SID.Value)
        }
    }
    $result = [string[]]@($memberships)
    [Array]::Sort($result, [StringComparer]::Ordinal)
    return $result
}

function Get-AccountObservation {
    $account = Get-LocalUser -Name $RunnerAccount -ErrorAction SilentlyContinue
    if ($null -eq $account) {
        return [ordered]@{
            exists = $false
            sid = $null
            enabled = $false
            purpose_verified = $false
            standard_user_verified = $false
            membership_sids = @()
        }
    }
    $memberships = @(Get-MembershipSids -AccountSid $account.SID)
    return [ordered]@{
        exists = $true
        sid = $account.SID
        enabled = [bool]$account.Enabled
        purpose_verified = ([string]$account.Description -ceq $PurposeDescription)
        standard_user_verified = (
            $memberships.Count -eq 1 -and $memberships[0] -ceq $UsersSid.Value
        )
        membership_sids = $memberships
    }
}

function Set-RunnerAccount {
    $account = Get-LocalUser -Name $RunnerAccount -ErrorAction SilentlyContinue
    if ($account -and [string]$account.Description -cne $PurposeDescription -and -not $AdoptExistingAccount) {
        throw "The existing local account is not purpose-bound; use -AdoptExistingAccount after manual review."
    }

    if (-not $account) {
        $password = Read-ConfirmedPassword
        try {
            $account = New-LocalUser -Name $RunnerAccount -Password $password `
                -Description $PurposeDescription -AccountNeverExpires -PasswordNeverExpires:$false `
                -UserMayNotChangePassword:$false
        }
        finally {
            $password.Dispose()
        }
    }
    else {
        if ($AdoptExistingAccount) {
            Set-LocalUser -Name $RunnerAccount -Description $PurposeDescription
        }
        if ($RotatePassword) {
            $password = Read-ConfirmedPassword
            try {
                Set-LocalUser -Name $RunnerAccount -Password $password
            }
            finally {
                $password.Dispose()
            }
        }
    }

    Set-LocalUser -Name $RunnerAccount -AccountNeverExpires -PasswordNeverExpires:$false `
        -UserMayChangePassword:$true
    Enable-LocalUser -Name $RunnerAccount
    $account = Get-LocalUser -Name $RunnerAccount
    foreach ($group in @(Get-LocalGroup)) {
        $members = @(Get-LocalGroupMember -Group $group.Name -ErrorAction Stop)
        $isMember = @($members | Where-Object { $_.SID -and $_.SID.Value -eq $account.SID.Value }).Count -gt 0
        if ($isMember -and $group.SID.Value -ne $UsersSid.Value) {
            Remove-LocalGroupMember -Group $group.Name -Member $account -Confirm:$false
        }
    }
    $usersGroup = Get-LocalGroup -SID $UsersSid
    $usersMembers = @(Get-LocalGroupMember -Group $usersGroup.Name -ErrorAction Stop)
    if (@($usersMembers | Where-Object { $_.SID -and $_.SID.Value -eq $account.SID.Value }).Count -eq 0) {
        Add-LocalGroupMember -Group $usersGroup.Name -Member $account
    }
}

function New-WorkspaceSecurity {
    param([Security.Principal.SecurityIdentifier]$RunnerSid)

    $security = [Security.AccessControl.DirectorySecurity]::new()
    $security.SetAccessRuleProtection($true, $false)
    $security.SetOwner($AdministratorsSid)
    $inheritance = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [Security.AccessControl.InheritanceFlags]::ObjectInherit
    $propagation = [Security.AccessControl.PropagationFlags]::None
    foreach ($sid in @($SystemSid, $AdministratorsSid)) {
        $security.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
            $sid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            $propagation,
            [Security.AccessControl.AccessControlType]::Allow
        ))
    }
    $operatorSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    foreach ($sid in @($operatorSid, $RunnerSid)) {
        $security.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
            $sid,
            [Security.AccessControl.FileSystemRights]::Modify,
            $inheritance,
            $propagation,
            [Security.AccessControl.AccessControlType]::Allow
        ))
    }
    return $security
}

function Set-WorkspaceBoundary {
    param([Security.Principal.SecurityIdentifier]$RunnerSid)

    $workspaceFull = [IO.Path]::GetFullPath($WorkspaceRoot)
    $signingFull = [IO.Path]::GetFullPath($SigningCustodyPath)
    if ($workspaceFull.StartsWith($signingFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
        $workspaceFull -ieq $signingFull) {
        throw "The Word workspace must be outside signing custody."
    }
    [void](New-Item -ItemType Directory -Path $workspaceFull -Force)
    foreach ($name in $WorkspaceDirectories) {
        [void](New-Item -ItemType Directory -Path (Join-Path $workspaceFull $name) -Force)
    }
    foreach ($path in @($workspaceFull) + @($WorkspaceDirectories | ForEach-Object { Join-Path $workspaceFull $_ })) {
        $item = Get-Item -LiteralPath $path -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "The Word workspace must not contain reparse-point boundaries."
        }
        Set-Acl -LiteralPath $path -AclObject (New-WorkspaceSecurity -RunnerSid $RunnerSid)
    }
}

function Get-WorkspaceObservation {
    param([Security.Principal.SecurityIdentifier]$RunnerSid)

    $paths = @([IO.Path]::GetFullPath($WorkspaceRoot)) + @(
        $WorkspaceDirectories | ForEach-Object { Join-Path ([IO.Path]::GetFullPath($WorkspaceRoot)) $_ }
    )
    if (@($paths | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Container) }).Count -gt 0) {
        return [ordered]@{ exists = $false; verified = $false; acl_hash = $ZeroHash }
    }
    $operatorSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $expectedRights = @{
        $SystemSid.Value = [int64][Security.AccessControl.FileSystemRights]::FullControl
        $AdministratorsSid.Value = [int64][Security.AccessControl.FileSystemRights]::FullControl
        $operatorSid = [int64][Security.AccessControl.FileSystemRights]::Modify
        $RunnerSid.Value = [int64][Security.AccessControl.FileSystemRights]::Modify
    }
    $expectedSids = @($expectedRights.Keys)
    $records = [Collections.Generic.List[string]]::new()
    $verified = $true
    foreach ($path in $paths) {
        $item = Get-Item -LiteralPath $path -Force
        $acl = Get-Acl -LiteralPath $path
        $ownerSid = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or -not $acl.AreAccessRulesProtected -or
            $ownerSid -ne $AdministratorsSid.Value) {
            $verified = $false
        }
        $rules = @($acl.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier]))
        if ($rules.Count -ne 4) { $verified = $false }
        foreach ($rule in $rules) {
            $sid = [string]$rule.IdentityReference.Value
            if ($expectedSids -notcontains $sid -or
                $rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
                $rule.InheritanceFlags -ne ([Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
                    [Security.AccessControl.InheritanceFlags]::ObjectInherit) -or
                [int64]$rule.FileSystemRights -ne $expectedRights[$sid]) {
                $verified = $false
            }
        }
        foreach ($sid in $expectedSids) {
            if (@($rules | Where-Object { $_.IdentityReference.Value -eq $sid }).Count -ne 1) {
                $verified = $false
            }
        }
        $records.Add((Get-Sha256String -Value ([string]$acl.Sddl)))
    }
    return [ordered]@{
        exists = $true
        verified = $verified
        acl_hash = Get-Sha256String -Value (($records | Sort-Object) -join "`n")
    }
}

function Set-SigningCustodyBoundary {
    param([Security.Principal.SecurityIdentifier]$RunnerSid)

    $item = Get-Item -LiteralPath $SigningCustodyPath -Force
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Signing custody must be an existing non-reparse-point directory."
    }
    $acl = Get-Acl -LiteralPath $item.FullName
    $acl.PurgeAccessRules($RunnerSid)
    $deny = [Security.AccessControl.FileSystemAccessRule]::new(
        $RunnerSid,
        [Security.AccessControl.FileSystemRights]::FullControl,
        ([Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit),
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Deny
    )
    $acl.AddAccessRule($deny)
    Set-Acl -LiteralPath $item.FullName -AclObject $acl
}

function Get-SigningObservation {
    param([Security.Principal.SecurityIdentifier]$RunnerSid)

    if (-not (Test-Path -LiteralPath $SigningCustodyPath -PathType Container)) {
        return [ordered]@{ exists = $false; deny_verified = $false; acl_hash = $ZeroHash }
    }
    $item = Get-Item -LiteralPath $SigningCustodyPath -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        return [ordered]@{ exists = $true; deny_verified = $false; acl_hash = $ZeroHash }
    }
    $acl = Get-Acl -LiteralPath $item.FullName
    $rules = @($acl.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier]))
    $deny = @($rules | Where-Object {
        $_.IdentityReference.Value -eq $RunnerSid.Value -and
        $_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Deny -and
        ($_.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -eq
            [Security.AccessControl.FileSystemRights]::FullControl
    })
    $allow = @($rules | Where-Object {
        $_.IdentityReference.Value -eq $RunnerSid.Value -and
        $_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow
    })
    return [ordered]@{
        exists = $true
        deny_verified = ($deny.Count -eq 1 -and $allow.Count -eq 0)
        acl_hash = Get-Sha256String -Value ([string]$acl.Sddl)
    }
}

function Get-FirewallRegistryObservation {
    param([string]$WordPath)

    $profilePaths = @(
        "HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\DomainProfile",
        "HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\StandardProfile",
        "HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\PublicProfile"
    )
    $profilesEnabled = $true
    foreach ($profilePath in $profilePaths) {
        try {
            $profile = Get-ItemProperty -LiteralPath $profilePath -ErrorAction Stop
            if ([int]$profile.EnableFirewall -ne 1) { $profilesEnabled = $false }
        }
        catch {
            $profilesEnabled = $false
        }
    }
    try {
        $registryRules = Get-ItemProperty -LiteralPath (
            "HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules"
        ) -ErrorAction Stop
    }
    catch {
        return [ordered]@{
            verified = $false; rule_verified = $false; profiles_enabled = $profilesEnabled
            rule_count = 0; rule_hash = $ZeroHash
        }
    }
    $normalizedWordPath = [IO.Path]::GetFullPath($WordPath)
    $matchingRecords = [Collections.Generic.List[string]]::new()
    $validCount = 0
    foreach ($property in $registryRules.PSObject.Properties) {
        if ($property.Name -like "PS*") { continue }
        $value = [string]$property.Value
        $fields = @($value.Split("|", [StringSplitOptions]::RemoveEmptyEntries))
        if ($fields -notcontains "Name=$FirewallRuleName") { continue }
        $matchingRecords.Add("$($property.Name)|$value")
        $matchesProgram = @($fields | Where-Object {
            $_.StartsWith("App=", [StringComparison]::OrdinalIgnoreCase) -and
            [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($_.Substring(4))) -ieq
                $normalizedWordPath
        }).Count -eq 1
        $limitsDestination = @($fields | Where-Object {
            $_.StartsWith("RA4=", [StringComparison]::OrdinalIgnoreCase) -or
            $_.StartsWith("RA6=", [StringComparison]::OrdinalIgnoreCase)
        }).Count -gt 0
        $limitsProfile = @($fields | Where-Object {
            $_.StartsWith("Profile=", [StringComparison]::OrdinalIgnoreCase)
        }).Count -gt 0
        if ($matchesProgram -and -not $limitsDestination -and -not $limitsProfile -and
            $fields -contains "Action=Block" -and $fields -contains "Active=TRUE" -and
            $fields -contains "Dir=Out") {
            $validCount += 1
        }
    }
    $ruleVerified = $matchingRecords.Count -eq 1 -and $validCount -eq 1
    return [ordered]@{
        verified = ($ruleVerified -and $profilesEnabled)
        rule_verified = $ruleVerified
        profiles_enabled = $profilesEnabled
        rule_count = $matchingRecords.Count
        rule_hash = if ($matchingRecords.Count -gt 0) {
            Get-Sha256String -Value (($matchingRecords | Sort-Object) -join "`n")
        } else { $ZeroHash }
    }
}

function Get-FirewallObservation {
    param([string]$WordPath)

    try {
        $profiles = @(Get-NetFirewallProfile -PolicyStore ActiveStore -ErrorAction Stop)
        $profilesEnabled = $profiles.Count -eq 3 -and
            @($profiles | Where-Object { $_.Enabled -ne $true }).Count -eq 0
        $rules = @(
            Get-NetFirewallRule -PolicyStore ActiveStore -DisplayName $FirewallRuleName -ErrorAction Stop
        )
        $records = [Collections.Generic.List[string]]::new()
        $ruleVerified = $rules.Count -eq 1
        $normalizedWordPath = [IO.Path]::GetFullPath($WordPath)
        foreach ($rule in $rules) {
            $applications = @($rule | Get-NetFirewallApplicationFilter -ErrorAction Stop)
            $addresses = @($rule | Get-NetFirewallAddressFilter -ErrorAction Stop)
            $programVerified = $applications.Count -eq 1 -and $applications[0].Program -and
                [IO.Path]::GetFullPath(
                    [Environment]::ExpandEnvironmentVariables([string]$applications[0].Program)
                ) -ieq $normalizedWordPath
            $addressVerified = $addresses.Count -eq 1 -and @($addresses[0].RemoteAddress) -contains "Any"
            if ([string]$rule.Enabled -ine "True" -or [string]$rule.Direction -ine "Outbound" -or
                [string]$rule.Action -ine "Block" -or [string]$rule.Profile -ine "Any" -or
                -not $programVerified -or -not $addressVerified) {
                $ruleVerified = $false
            }
            $records.Add("$($rule.Name)|$($rule.Profile)|$($rule.Direction)|$($rule.Action)|" +
                "$normalizedWordPath|Any")
        }
        return [ordered]@{
            verified = ($ruleVerified -and $profilesEnabled)
            rule_verified = $ruleVerified
            profiles_enabled = $profilesEnabled
            rule_count = $rules.Count
            rule_hash = if ($records.Count -gt 0) {
                Get-Sha256String -Value (($records | Sort-Object) -join "`n")
            } else { $ZeroHash }
        }
    }
    catch {
        return Get-FirewallRegistryObservation -WordPath $WordPath
    }
}

function Set-FirewallBoundary {
    param([string]$WordPath)

    $current = Get-FirewallObservation -WordPath $WordPath
    if ($current.rule_count -gt 0 -and -not $current.rule_verified -and -not $ReplaceDriftedFirewallRule) {
        throw "The named firewall rule drifted; use -ReplaceDriftedFirewallRule after manual review."
    }
    if ($current.rule_count -gt 0 -and -not $current.rule_verified) {
        Get-NetFirewallRule -DisplayName $FirewallRuleName | Remove-NetFirewallRule -Confirm:$false
    }
    if ($current.rule_count -eq 0 -or -not $current.rule_verified) {
        [void](New-NetFirewallRule -DisplayName $FirewallRuleName -Direction Outbound -Action Block `
            -Program $WordPath -RemoteAddress Any -Profile Any -Enabled True)
    }
}

if ($Mode -eq "Audit" -and ($AdoptExistingAccount -or $RotatePassword -or $ReplaceDriftedFirewallRule)) {
    throw "Mutation switches are valid only in Apply mode."
}
foreach ($command in @("Get-LocalUser", "Get-LocalGroup", "Get-NetFirewallRule", "Get-NetFirewallProfile")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "A required Windows administration command is unavailable: $command"
    }
}
if ($Mode -eq "Apply" -and -not (Test-IsAdministrator)) {
    throw "Apply mode requires an elevated Windows PowerShell session."
}
if ($Mode -eq "Apply" -and (-not [Environment]::UserInteractive -or (Get-Process -Id $PID).SessionId -eq 0)) {
    throw "Apply mode requires a visible interactive Windows session."
}

Assert-LocalFixedPath -Path $WorkspaceRoot -Label "The Word workspace"
Assert-LocalFixedPath -Path $SigningCustodyPath -Label "Signing custody"
Assert-LocalFixedPath -Path $OutputPath -Label "The bootstrap report"
Assert-NewJsonPath -Path $OutputPath

$wordPath = Get-WordExecutable
if (-not $wordPath) {
    throw "Microsoft Word is not available at an approved executable path."
}
if ($Mode -eq "Apply") {
    if (-not (Test-Path -LiteralPath $SigningCustodyPath -PathType Container)) {
        throw "Signing custody must exist before host hardening."
    }
    $signingItem = Get-Item -LiteralPath $SigningCustodyPath -Force
    if ($signingItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Signing custody must not be a reparse point."
    }
    if (Test-Path -LiteralPath $WorkspaceRoot) {
        $workspaceItem = Get-Item -LiteralPath $WorkspaceRoot -Force
        if (-not $workspaceItem.PSIsContainer -or
            ($workspaceItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "The Word workspace must be a non-reparse-point directory."
        }
    }
    $initialFirewall = Get-FirewallObservation -WordPath $wordPath
    if ($initialFirewall.rule_count -gt 0 -and -not $initialFirewall.rule_verified -and
        -not $ReplaceDriftedFirewallRule) {
        throw "The named firewall rule drifted; use -ReplaceDriftedFirewallRule after manual review."
    }
    Set-RunnerAccount
    $account = Get-AccountObservation
    Set-WorkspaceBoundary -RunnerSid $account.sid
    Set-SigningCustodyBoundary -RunnerSid $account.sid
    Set-FirewallBoundary -WordPath $wordPath
}

$account = Get-AccountObservation
$workspace = if ($account.exists) {
    Get-WorkspaceObservation -RunnerSid $account.sid
} else { [ordered]@{ exists = $false; verified = $false; acl_hash = $ZeroHash } }
$signing = if ($account.exists) {
    Get-SigningObservation -RunnerSid $account.sid
} else { [ordered]@{ exists = $false; deny_verified = $false; acl_hash = $ZeroHash } }
$firewall = Get-FirewallObservation -WordPath $wordPath
$blocking = [Collections.Generic.List[string]]::new()
if (-not $account.exists) { $blocking.Add("dedicated_local_account_absent") }
if ($account.exists -and -not $account.purpose_verified) { $blocking.Add("dedicated_local_account_purpose_not_verified") }
if ($account.exists -and -not $account.enabled) { $blocking.Add("dedicated_local_account_disabled") }
if ($account.exists -and -not $account.standard_user_verified) { $blocking.Add("dedicated_local_account_privilege_not_verified") }
if (-not $workspace.verified) { $blocking.Add("workspace_acl_not_verified") }
if (-not $signing.deny_verified) { $blocking.Add("signing_custody_deny_not_verified") }
if (-not $firewall.profiles_enabled) { $blocking.Add("windows_firewall_profiles_not_enabled") }
if (-not $firewall.verified) { $blocking.Add("winword_outbound_firewall_block_not_verified") }

$operatorSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$profilesRoot = Split-Path -Parent ([Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile))
$profilePath = Join-Path $profilesRoot $RunnerAccount
$report = [ordered]@{
    schema_version = "genoffice_docx_word_host_bootstrap_report.v1"
    observed_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    mode = $Mode.ToLowerInvariant()
    bootstrap_script_sha256 = Get-Sha256File -Path $PSCommandPath
    operator_account_sid_sha256 = Get-Sha256String -Value $operatorSid
    runner_account_sid_sha256 = if ($account.exists) { Get-Sha256String -Value $account.sid.Value } else { $ZeroHash }
    runner_account_exists = [bool]$account.exists
    runner_account_enabled = [bool]$account.enabled
    runner_account_purpose_verified = [bool]$account.purpose_verified
    runner_account_standard_user_verified = [bool]$account.standard_user_verified
    runner_local_group_membership_count = @($account.membership_sids).Count
    runner_profile_initialized = Test-Path -LiteralPath $profilePath -PathType Container
    word_executable_sha256 = Get-Sha256File -Path $wordPath
    word_executable_path_sha256 = Get-Sha256String -Value ([IO.Path]::GetFullPath($wordPath))
    word_version = [string](Get-Item -LiteralPath $wordPath).VersionInfo.FileVersion
    workspace_path_sha256 = Get-Sha256String -Value ([IO.Path]::GetFullPath($WorkspaceRoot))
    workspace_exists = [bool]$workspace.exists
    workspace_acl_verified = [bool]$workspace.verified
    workspace_acl_sha256 = [string]$workspace.acl_hash
    signing_custody_path_sha256 = Get-Sha256String -Value ([IO.Path]::GetFullPath($SigningCustodyPath))
    signing_custody_exists = [bool]$signing.exists
    signing_custody_runner_deny_verified = [bool]$signing.deny_verified
    signing_custody_acl_sha256 = [string]$signing.acl_hash
    firewall_rule_name_sha256 = Get-Sha256String -Value $FirewallRuleName
    firewall_rule_count = [int]$firewall.rule_count
    firewall_profiles_enabled = [bool]$firewall.profiles_enabled
    outbound_firewall_block_verified = [bool]$firewall.verified
    network_isolation_rule_sha256 = [string]$firewall.rule_hash
    bootstrap_ready = $blocking.Count -eq 0
    blocking_reasons = [string[]]@($blocking)
    next_step_requires_local_interactive_logon = $true
    password_included = $false
    tenant_content_included = $false
    document_content_included = $false
    private_key_included = $false
}
Write-NewJson -Path $OutputPath -Value $report
if ($report.bootstrap_ready) { exit 0 }
exit 2
