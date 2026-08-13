[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Preflight", "Run")]
    [string]$Mode,

    [Parameter(Mandatory = $true, ParameterSetName = "Preflight")]
    [string]$OutputPath,

    [Parameter(Mandatory = $true, ParameterSetName = "Run")]
    [string]$AssignmentRoot,

    [Parameter(Mandatory = $true, ParameterSetName = "Run")]
    [string]$HandoffRoot,

    [string]$ExpectedRunnerAccount = "collabio-word-runner",
    [string]$SigningCustodyPath = "C:\Users\tkirchherr\.collabio\signing"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ZeroHash = "sha256:" + ("0" * 64)
$ExpectedFirewallRuleName = "Collabio Word fidelity outbound deny"
$AllowedFixtures = @(
    "formatting-table-fidelity",
    "headers-comments-footnotes-fidelity",
    "unknown-markup-passthrough"
)
$ExpectedPreflightPolicyHash = "sha256:85412a0449bd8dba0a64dc07d43877179f490bac12b5e17533fc95825eec564f"
$ExpectedCorpusManifestHash = "sha256:1ba8a7c118f7979dadbbb4e530a4ab16206b76e46104daadc0f0a46f2c568908"
$ExpectedFidelityPolicyHash = "sha256:22d414df142a2d730a94212b2f52a9d9b4641e68ee9f5226e6f032c57ee197b2"
$ExpectedStudyPlanHash = "sha256:deb5682c4e78bb7ab8e3368eb63395ff4244803f03a11132cef04d998c082da8"
$ExpectedFixtureHashes = @{
    "formatting-table-fidelity" = "sha256:5d6380b0b725e7489ddb59143f330f6066fd850f546a67292d325b0bd3543d3c"
    "headers-comments-footnotes-fidelity" = "sha256:4a01a98bcf1bc6fa04f545986051e04f1657a08b14aac0f5b07b8826047bb10d"
    "unknown-markup-passthrough" = "sha256:3863ed1cf1849a37d0af6d015c2f3d2002439e75ee509999910b1fabde8e6163"
}
$ExpectedPipelineSteps = @(
    "source_preflight",
    "interactive_windows_session_revalidation",
    "dedicated_local_account_revalidation",
    "winword_outbound_firewall_block_revalidation",
    "office_identity_absence_revalidation",
    "signing_custody_inaccessibility_revalidation",
    "visible_word_client_start",
    "macro_force_disable",
    "read_only_source_open",
    "same_engine_source_pdf_export",
    "explicit_human_confirmation",
    "word_docx_roundtrip_save_as",
    "same_engine_candidate_pdf_export",
    "write_once_public_handoff",
    "source_blind_output_preflight",
    "output_structural_fingerprint",
    "open_xml_sdk_validation_office2021",
    "pdftoppm_raw_rgb_144_dpi",
    "integer_visual_measurement",
    "write_once_evidence_receipt",
    "external_ed25519_signature_handoff"
)
$HostBlockingReasons = @(
    "dedicated_local_account_not_verified",
    "interactive_user_session_not_verified",
    "office_identity_or_tenant_credentials_present",
    "signing_custody_accessible",
    "winword_not_available",
    "winword_outbound_firewall_block_not_verified",
    "word_process_already_running"
)

function Get-Sha256Bytes {
    param([byte[]]$Content)

    $sha = [System.Security.Cryptography.SHA256]::Create()
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
        throw "A required input is not a regular file."
    }
    $stream = [IO.File]::Open($item.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return "sha256:" + ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function ConvertTo-CanonicalJson {
    param($Value)

    if ($null -eq $Value) {
        return "null"
    }
    if ($Value -is [bool]) {
        if ($Value) { return "true" }
        return "false"
    }
    if ($Value -is [byte] -or $Value -is [sbyte] -or $Value -is [int16] -or
        $Value -is [uint16] -or $Value -is [int32] -or $Value -is [uint32] -or
        $Value -is [int64] -or $Value -is [uint64] -or $Value -is [decimal] -or
        $Value -is [double] -or $Value -is [single]) {
        return [Convert]::ToString($Value, [Globalization.CultureInfo]::InvariantCulture)
    }
    if ($Value -is [datetime]) {
        return ConvertTo-Json -Compress -InputObject $Value.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ")
    }
    if ($Value -is [string]) {
        return ConvertTo-Json -Compress -InputObject $Value
    }
    if ($Value -is [Collections.IDictionary]) {
        $names = [string[]]@($Value.Keys | ForEach-Object { [string]$_ })
        [Array]::Sort($names, [StringComparer]::Ordinal)
        $members = foreach ($name in $names) {
            (ConvertTo-Json -Compress -InputObject $name) + ":" + (ConvertTo-CanonicalJson -Value $Value[$name])
        }
        return "{" + ($members -join ",") + "}"
    }
    if ($Value -is [Collections.IEnumerable]) {
        $members = foreach ($item in $Value) {
            ConvertTo-CanonicalJson -Value $item
        }
        return "[" + ($members -join ",") + "]"
    }
    $propertyNames = [string[]]@($Value.PSObject.Properties.Name)
    [Array]::Sort($propertyNames, [StringComparer]::Ordinal)
    $properties = foreach ($name in $propertyNames) {
        (ConvertTo-Json -Compress -InputObject $name) + ":" + (ConvertTo-CanonicalJson -Value $Value.$name)
    }
    return "{" + ($properties -join ",") + "}"
}

function Write-NewUtf8Json {
    param([string]$Path, $Value)

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "The output parent directory does not exist."
    }
    $json = (ConvertTo-Json -InputObject $Value -Depth 12) + "`n"
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json)
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally {
        $stream.Dispose()
    }
}

function Get-ModelHash {
    param($Value, [string]$HashField)

    $content = [ordered]@{}
    foreach ($property in $Value.PSObject.Properties) {
        if ($property.Name -cne $HashField) {
            $content[$property.Name] = $property.Value
        }
    }
    return Get-Sha256String -Value (ConvertTo-CanonicalJson -Value $content)
}

function Copy-NewFile {
    param([string]$Source, [string]$Destination)

    $sourceStream = [IO.File]::Open($Source, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        $destinationStream = [IO.File]::Open(
            $Destination,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::None
        )
        try {
            $sourceStream.CopyTo($destinationStream)
            $destinationStream.Flush($true)
        }
        finally {
            $destinationStream.Dispose()
        }
    }
    finally {
        $sourceStream.Dispose()
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
            return (Get-Item -LiteralPath $candidate -Force).FullName
        }
    }
    return $null
}

function Get-FontInventory {
    $fontKeys = @(
        "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts",
        "HKCU:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
    )
    $fonts = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($key in $fontKeys) {
        if (-not (Test-Path -LiteralPath $key)) { continue }
        $properties = (Get-ItemProperty -LiteralPath $key).PSObject.Properties
        foreach ($property in $properties) {
            if ($property.Name -notlike "PS*") {
                [void]$fonts.Add([string]$property.Name)
            }
        }
    }
    $result = [string[]]@($fonts)
    [Array]::Sort($result, [StringComparer]::Ordinal)
    return $result
}

function Test-RegistryChildrenAbsent {
    param([string[]]$Paths)

    foreach ($path in $Paths) {
        if (Test-Path -LiteralPath $path) {
            if (@(Get-ChildItem -LiteralPath $path -Force -ErrorAction SilentlyContinue).Count -gt 0) {
                return $false
            }
        }
    }
    return $true
}

function Get-NetworkIsolationObservation {
    param([string]$WordPath)

    if (-not $WordPath -or -not (Get-Command Get-NetFirewallRule -ErrorAction SilentlyContinue)) {
        return [ordered]@{ verified = $false; rule_hash = $ZeroHash }
    }
    $normalizedWordPath = [IO.Path]::GetFullPath($WordPath)
    $records = [Collections.Generic.List[string]]::new()
    try {
        $rules = Get-NetFirewallRule -PolicyStore ActiveStore -Enabled True -Direction Outbound -Action Block
    }
    catch {
        $firewallProfilePaths = @(
            "HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\DomainProfile",
            "HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\StandardProfile",
            "HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\PublicProfile"
        )
        $profilesEnabled = $true
        foreach ($profilePath in $firewallProfilePaths) {
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
            return [ordered]@{ verified = $false; rule_hash = $ZeroHash }
        }
        foreach ($property in $registryRules.PSObject.Properties) {
            if ($property.Name -like "PS*") { continue }
            $value = [string]$property.Value
            $fields = @($value.Split("|", [StringSplitOptions]::RemoveEmptyEntries))
            $matchesIdentity = $fields -contains "Name=$ExpectedFirewallRuleName"
            $matchesProgram = @($fields | Where-Object {
                $_.StartsWith("App=", [StringComparison]::OrdinalIgnoreCase) -and
                [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($_.Substring(4))) -ieq $normalizedWordPath
            }).Count -eq 1
            $blocksEveryDestination = @($fields | Where-Object {
                $_.StartsWith("RA4=", [StringComparison]::OrdinalIgnoreCase) -or
                $_.StartsWith("RA6=", [StringComparison]::OrdinalIgnoreCase)
            }).Count -eq 0
            if ($profilesEnabled -and $matchesIdentity -and $matchesProgram -and $blocksEveryDestination -and
                $fields -contains "Action=Block" -and $fields -contains "Active=TRUE" -and
                $fields -contains "Dir=Out") {
                return [ordered]@{
                    verified = $true
                    rule_hash = Get-Sha256String -Value "$($property.Name)|$value"
                }
            }
        }
        return [ordered]@{ verified = $false; rule_hash = $ZeroHash }
    }
    foreach ($rule in $rules) {
        $applications = @($rule | Get-NetFirewallApplicationFilter)
        $addresses = @($rule | Get-NetFirewallAddressFilter)
        $blocksProgram = @($applications | Where-Object {
            $_.Program -and $_.Program -ne "Any" -and
            [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables([string]$_.Program)) -ieq $normalizedWordPath
        }).Count -gt 0
        $blocksAllDestinations = @($addresses | Where-Object {
            $_.RemoteAddress -eq "Any" -or @($_.RemoteAddress) -contains "Any"
        }).Count -gt 0
        if ($rule.DisplayName -ceq $ExpectedFirewallRuleName -and $blocksProgram -and $blocksAllDestinations) {
            $records.Add("$($rule.Name)|$($rule.Profile)|$($rule.Direction)|$($rule.Action)|$normalizedWordPath|Any")
        }
    }
    $recordArray = [string[]]@($records)
    [Array]::Sort($recordArray, [StringComparer]::Ordinal)
    if ($recordArray.Count -eq 0) {
        return [ordered]@{ verified = $false; rule_hash = $ZeroHash }
    }
    return [ordered]@{
        verified = $true
        rule_hash = Get-Sha256String -Value ($recordArray -join "`n")
    }
}

function Test-SigningCustodyAccessible {
    try {
        [void](Get-Item -LiteralPath $SigningCustodyPath -Force -ErrorAction Stop)
        return $true
    }
    catch [System.Management.Automation.ItemNotFoundException] {
        return $false
    }
    catch [System.UnauthorizedAccessException] {
        return $false
    }
    catch {
        return $false
    }
}

function Get-HostReadinessReport {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $accountName = [string]$identity.Name
    $accountParts = $accountName.Split("\", 2)
    $dedicatedAccount = $accountParts.Count -eq 2 -and
        $accountParts[0] -ieq $env:COMPUTERNAME -and
        $accountParts[1] -ceq $ExpectedRunnerAccount
    $sessionId = [Diagnostics.Process]::GetCurrentProcess().SessionId
    $interactive = [Environment]::UserInteractive
    $sessionZeroAbsent = $sessionId -ne 0
    $identityPaths = @(
        "HKCU:\Software\Microsoft\Office\16.0\Common\Identity\Identities",
        "HKCU:\Software\Microsoft\IdentityCRL\StoredIdentities",
        "HKCU:\Software\Microsoft\OneAuth\Accounts",
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\AAD\Storage"
    )
    $officeIdentityAbsent = Test-RegistryChildrenAbsent -Paths $identityPaths
    $tenantCredentialsAvailable = -not $officeIdentityAbsent
    $signingCustodyAccessible = Test-SigningCustodyAccessible
    $wordPath = Get-WordExecutable
    $wordInstalled = $null -ne $wordPath
    $wordHash = if ($wordInstalled) { Get-Sha256File -Path $wordPath } else { $ZeroHash }
    $wordVersion = if ($wordInstalled) {
        [string](Get-Item -LiteralPath $wordPath).VersionInfo.FileVersion
    } else { "unavailable" }
    $network = Get-NetworkIsolationObservation -WordPath $wordPath
    $wordProcessAbsent = @(Get-Process -Name WINWORD -ErrorAction SilentlyContinue).Count -eq 0
    $fonts = @(Get-FontInventory)
    $fontHash = Get-Sha256String -Value ($fonts -join "`n")
    $windows = Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    $displayVersion = if ($windows.DisplayVersion) { [string]$windows.DisplayVersion } else { "unavailable" }
    $build = [string]$windows.CurrentBuild
    if ($windows.UBR -ne $null) { $build = "$build.$($windows.UBR)" }
    $architecture = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }

    $checks = [ordered]@{
        dedicated_local_account_not_verified = $dedicatedAccount
        interactive_user_session_not_verified = ($interactive -and $sessionZeroAbsent)
        office_identity_or_tenant_credentials_present = ($officeIdentityAbsent -and -not $tenantCredentialsAvailable)
        signing_custody_accessible = -not $signingCustodyAccessible
        winword_not_available = $wordInstalled
        winword_outbound_firewall_block_not_verified = [bool]$network.verified
        word_process_already_running = $wordProcessAbsent
    }
    $blocking = @($HostBlockingReasons | Where-Object { -not $checks[$_] })
    return [ordered]@{
        schema_version = "genoffice_docx_word_host_readiness_report.v1"
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        runner_script_sha256 = Get-Sha256File -Path $PSCommandPath
        operator_account_sid_sha256 = Get-Sha256String -Value ([string]$identity.User.Value)
        word_executable_sha256 = $wordHash
        word_version = $wordVersion
        windows_product_name = [string]$windows.ProductName
        windows_display_version = $displayVersion
        windows_build = $build
        process_architecture = $architecture
        powershell_version = [string]$PSVersionTable.PSVersion
        font_inventory = $fonts
        font_count = $fonts.Count
        normalized_font_inventory_sha256 = $fontHash
        network_isolation_rule_sha256 = [string]$network.rule_hash
        dedicated_local_account_verified = $dedicatedAccount
        interactive_user_session_verified = $interactive
        session_zero_absent = $sessionZeroAbsent
        office_identity_absent = $officeIdentityAbsent
        tenant_credentials_available = $tenantCredentialsAvailable
        signing_custody_accessible = $signingCustodyAccessible
        winword_installed = $wordInstalled
        outbound_firewall_block_verified = [bool]$network.verified
        word_process_absent = $wordProcessAbsent
        host_ready = $blocking.Count -eq 0
        blocking_reasons = $blocking
        source_synthetic_only = $true
        tenant_content_included = $false
        document_content_included = $false
        private_key_included = $false
    }
}

function Assert-ExactDirectory {
    param([string]$Path, [string[]]$ExpectedNames, [bool]$Directories)

    $directory = Get-Item -LiteralPath $Path -Force
    if (-not $directory.PSIsContainer -or ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "An assignment directory is invalid."
    }
    $items = @(Get-ChildItem -LiteralPath $directory.FullName -Force)
    $actualNames = [string[]]@($items.Name)
    $expected = [string[]]@($ExpectedNames)
    [Array]::Sort($actualNames, [StringComparer]::Ordinal)
    [Array]::Sort($expected, [StringComparer]::Ordinal)
    if (($actualNames -join "`n") -cne ($expected -join "`n")) {
        throw "An assignment inventory is not exact."
    }
    foreach ($item in $items) {
        if ($item.PSIsContainer -ne $Directories -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "An assignment entry is invalid."
        }
    }
}

function Assert-EqualArray {
    param($Actual, $Expected, [string]$Label)

    if ((@($Actual) -join "`n") -cne (@($Expected) -join "`n")) {
        throw "$Label drifted."
    }
}

function Assert-HostBinding {
    param($Expected, $Observed)

    $fields = @(
        "runner_script_sha256", "operator_account_sid_sha256", "word_executable_sha256", "word_version",
        "windows_product_name", "windows_display_version", "windows_build", "process_architecture",
        "powershell_version", "font_count", "normalized_font_inventory_sha256",
        "network_isolation_rule_sha256", "dedicated_local_account_verified",
        "interactive_user_session_verified", "session_zero_absent", "office_identity_absent",
        "tenant_credentials_available", "signing_custody_accessible", "winword_installed",
        "outbound_firewall_block_verified", "word_process_absent", "host_ready"
    )
    foreach ($field in $fields) {
        if ($Expected.$field -cne $Observed.$field) {
            throw "The Word host readiness binding drifted."
        }
    }
    Assert-EqualArray -Actual $Observed.font_inventory -Expected $Expected.font_inventory -Label "Font inventory"
    Assert-EqualArray -Actual $Observed.blocking_reasons -Expected $Expected.blocking_reasons -Label "Host blockers"
    if (-not $Observed.host_ready) {
        throw "The Word host is not ready."
    }
}

function Assert-RunRequest {
    param(
        $Request,
        $Host,
        [string]$HostReportPath,
        [string]$SourcePath,
        [string]$CorpusPath,
        [string]$StudyPlanPath
    )

    if ($Request.schema_version -cne "genoffice_docx_word_run_request.v1" -or
        $Request.engine_id -cne "microsoft_word" -or
        $Request.runner_mode -cne "interactive_windows_client" -or
        $AllowedFixtures -cnotcontains $Request.fixture_id -or
        $Request.assignment_id -cne "microsoft_word:$($Request.fixture_id)" -or
        $Request.request_id -cne "run-request:$($Request.assignment_id)" -or
        $Request.source_filename -cne "$($Request.fixture_id).docx") {
        throw "The Word run-request scope is invalid."
    }
    Assert-EqualArray -Actual $Request.pipeline_steps -Expected $ExpectedPipelineSteps -Label "Pipeline"
    $requiredTrue = @(
        "source_synthetic", "interactive_user_session_required", "visible_word_client_required",
        "explicit_human_confirmation_required", "network_isolation_required",
        "dedicated_local_account_required", "engine_execution_allowed"
    )
    $requiredFalse = @(
        "unattended_execution_allowed", "tenant_content_allowed", "tenant_credentials_allowed",
        "signing_custody_access_allowed", "private_key_allowed", "persistent_product_write_allowed",
        "external_side_effect_allowed"
    )
    foreach ($field in $requiredTrue) { if ($Request.$field -ne $true) { throw "The Word run-request is not fail-closed." } }
    foreach ($field in $requiredFalse) { if ($Request.$field -ne $false) { throw "The Word run-request is not fail-closed." } }
    if ($Request.max_docx_bytes -ne 16777216 -or $Request.max_pdf_bytes -ne 134217728 -or
        $Request.max_page_count -ne 32 -or $Request.max_page_dimension_pixels -ne 4096 -or
        $Request.raster_dpi -ne 144 -or
        $Request.execution_authorization_basis -cne "explicit_synthetic_interactive_study_run_request") {
        throw "The Word run-request resource policy drifted."
    }
    $expectedSourceHash = [string]$ExpectedFixtureHashes[[string]$Request.fixture_id]
    if (-not $expectedSourceHash -or $Request.source_content_sha256 -cne $expectedSourceHash -or
        $Request.preflight_policy_hash -cne $ExpectedPreflightPolicyHash -or
        $Request.corpus_manifest_hash -cne $ExpectedCorpusManifestHash -or
        $Request.fidelity_policy_hash -cne $ExpectedFidelityPolicyHash -or
        $Request.study_plan_hash -cne $ExpectedStudyPlanHash) {
        throw "The Word run-request is not anchored to the reviewed synthetic study."
    }
    if ((Get-Sha256File -Path $HostReportPath) -cne $Request.host_readiness_report_sha256 -or
        (Get-Sha256File -Path $PSCommandPath) -cne $Request.runner_script_sha256 -or
        (Get-Sha256File -Path $SourcePath) -cne $Request.source_content_sha256 -or
        $Host.runner_script_sha256 -cne $Request.runner_script_sha256 -or
        $Host.operator_account_sid_sha256 -cne $Request.operator_account_sid_sha256 -or
        $Host.word_executable_sha256 -cne $Request.word_executable_sha256 -or
        $Host.network_isolation_rule_sha256 -cne $Request.network_isolation_rule_sha256) {
        throw "The Word run-request artifact binding drifted."
    }
    if ((Get-ModelHash -Value $Request -HashField "request_hash") -cne $Request.request_hash) {
        throw "The Word run-request hash is invalid."
    }
    $requested = [DateTimeOffset]::Parse([string]$Request.requested_at_utc).ToUniversalTime()
    $expires = [DateTimeOffset]::Parse([string]$Request.expires_at_utc).ToUniversalTime()
    $now = [DateTimeOffset]::UtcNow
    if ($requested -gt $now -or $expires -lt $now -or $expires -le $requested -or
        ($expires - $requested).TotalHours -gt 8) {
        throw "The Word run-request is outside its permitted lifetime."
    }
    $sourceItem = Get-Item -LiteralPath $SourcePath -Force
    if ($sourceItem.Length -le 0 -or $sourceItem.Length -gt $Request.max_docx_bytes) {
        throw "The synthetic Word source size is invalid."
    }
    $corpus = Get-Content -LiteralPath $CorpusPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $studyPlan = Get-Content -LiteralPath $StudyPlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($corpus.manifest_hash -cne $ExpectedCorpusManifestHash -or
        (Get-ModelHash -Value $corpus -HashField "manifest_hash") -cne $corpus.manifest_hash -or
        $studyPlan.plan_hash -cne $ExpectedStudyPlanHash -or
        (Get-ModelHash -Value $studyPlan -HashField "plan_hash") -cne $studyPlan.plan_hash -or
        $studyPlan.fidelity_policy_hash -cne $ExpectedFidelityPolicyHash -or
        $studyPlan.preflight_policy_hash -cne $ExpectedPreflightPolicyHash -or
        $studyPlan.corpus_manifest_hash -cne $ExpectedCorpusManifestHash) {
        throw "The Word study plan or corpus manifest is invalid."
    }
    $artifact = @($corpus.artifacts | Where-Object { $_.fixture_id -ceq $Request.fixture_id })
    $studyAssignment = @($studyPlan.assignments | Where-Object { $_.assignment_id -ceq $Request.assignment_id })
    if ($artifact.Count -ne 1 -or $artifact[0].filename -cne $Request.source_filename -or
        $artifact[0].category -cne "fidelity" -or $artifact[0].future_engine_evaluation_eligible -ne $true -or
        $artifact[0].content_sha256 -cne $Request.source_content_sha256 -or
        $studyAssignment.Count -ne 1 -or
        $studyAssignment[0].source_content_sha256 -cne $Request.source_content_sha256 -or
        $corpus.tenant_content_included -ne $false -or $corpus.customer_content_included -ne $false) {
        throw "The Word source is not bound to the synthetic fidelity corpus."
    }
}

function Invoke-VisibleWordRoundTrip {
    param([string]$SourcePath, [string]$Workspace)

    Add-Type -AssemblyName System.Windows.Forms
    $outputDocx = Join-Path $Workspace "output.docx"
    $referencePdf = Join-Path $Workspace "reference.pdf"
    $candidatePdf = Join-Path $Workspace "candidate.pdf"
    $word = $null
    $document = $null
    $oldAutomationSecurity = $null
    $started = [DateTimeOffset]::UtcNow
    $confirmed = $null
    try {
        $word = New-Object -ComObject Word.Application
        $oldAutomationSecurity = $word.AutomationSecurity
        $word.AutomationSecurity = 3
        $word.Visible = $true
        $word.DisplayAlerts = -1
        $word.Options.UpdateLinksAtOpen = $false
        $document = $word.Documents.Open($SourcePath, $false, $true, $false)
        if (-not $word.Visible -or -not $document.ReadOnly) {
            throw "Word did not honor the visible read-only contract."
        }
        $document.ExportAsFixedFormat($referencePdf, 17, $false, 0, 0, 1, 1, 0, $false, $false, 0, $true, $true, $false)
        $message = "Synthetic Collabio fidelity fixture only.`n`nConfirm that Word is visible and the document is ready for the controlled round-trip."
        $answer = [Windows.Forms.MessageBox]::Show(
            $message,
            "Collabio Word fidelity",
            [Windows.Forms.MessageBoxButtons]::OKCancel,
            [Windows.Forms.MessageBoxIcon]::Information,
            [Windows.Forms.MessageBoxDefaultButton]::Button2
        )
        if ($answer -ne [Windows.Forms.DialogResult]::OK) {
            throw "The operator did not confirm the interactive Word run."
        }
        $confirmed = [DateTimeOffset]::UtcNow
        $document.SaveAs2($outputDocx, 16, $false, "", $false)
        $document.ExportAsFixedFormat($candidatePdf, 17, $false, 0, 0, 1, 1, 0, $false, $false, 0, $true, $true, $false)
        $document.Close(0)
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($document)
        $document = $null
        $word.AutomationSecurity = $oldAutomationSecurity
        $word.Quit()
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($word)
        $word = $null
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
        Start-Sleep -Milliseconds 500
        if (@(Get-Process -Name WINWORD -ErrorAction SilentlyContinue).Count -ne 0) {
            throw "Word remained active after the controlled run."
        }
        foreach ($path in @($outputDocx, $referencePdf, $candidatePdf)) {
            if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or (Get-Item -LiteralPath $path).Length -le 0) {
                throw "Word did not create the exact handoff artifacts."
            }
        }
        return [ordered]@{
            started_at_utc = $started.ToString("o")
            human_confirmed_at_utc = $confirmed.ToString("o")
            completed_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
            output_docx = $outputDocx
            reference_pdf = $referencePdf
            candidate_pdf = $candidatePdf
        }
    }
    finally {
        if ($document -ne $null) {
            try { $document.Close(0) } catch {}
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($document)
        }
        if ($word -ne $null) {
            try {
                if ($oldAutomationSecurity -ne $null) { $word.AutomationSecurity = $oldAutomationSecurity }
                $word.Quit()
            } catch {}
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($word)
        }
    }
}

if ($MyInvocation.InvocationName -eq ".") {
    return
}

if ($Mode -eq "Preflight") {
    $report = Get-HostReadinessReport
    Write-NewUtf8Json -Path ([IO.Path]::GetFullPath($OutputPath)) -Value $report
    Write-Output (ConvertTo-Json -InputObject $report -Depth 8 -Compress)
    if (-not $report.host_ready) { exit 2 }
    exit 0
}

$assignment = [IO.Path]::GetFullPath($AssignmentRoot)
$handoff = [IO.Path]::GetFullPath($HandoffRoot)
Assert-ExactDirectory -Path $assignment -ExpectedNames @("control", "input", "runner") -Directories $true
$control = Join-Path $assignment "control"
$inputDirectory = Join-Path $assignment "input"
$runnerDirectory = Join-Path $assignment "runner"
Assert-ExactDirectory -Path $control -ExpectedNames @(
    "corpus-manifest.json", "host-readiness-report.json", "run-request.json", "study-plan.json"
) -Directories $false
Assert-ExactDirectory -Path $runnerDirectory -ExpectedNames @("Invoke-CollabioWordFidelity.ps1") -Directories $false
$requestPath = Join-Path $control "run-request.json"
$hostPath = Join-Path $control "host-readiness-report.json"
$corpusPath = Join-Path $control "corpus-manifest.json"
$request = Get-Content -LiteralPath $requestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$host = Get-Content -LiteralPath $hostPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-ExactDirectory -Path $inputDirectory -ExpectedNames @([string]$request.source_filename) -Directories $false
$sourcePath = Join-Path $inputDirectory ([string]$request.source_filename)
$observedHost = Get-HostReadinessReport
Assert-HostBinding -Expected $host -Observed $observedHost
Assert-RunRequest `
    -Request $request `
    -Host $host `
    -HostReportPath $hostPath `
    -SourcePath $sourcePath `
    -CorpusPath $corpusPath `
    -StudyPlanPath (Join-Path $control "study-plan.json")

$handoffItem = Get-Item -LiteralPath $handoff -Force
if (-not $handoffItem.PSIsContainer -or ($handoffItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
    @(Get-ChildItem -LiteralPath $handoff -Force).Count -ne 0) {
    throw "The Word handoff directory is invalid or not empty."
}
$workspace = Join-Path ([IO.Path]::GetTempPath()) ("collabio-word-fidelity-" + [Guid]::NewGuid().ToString("N"))
[void](New-Item -ItemType Directory -Path $workspace)
try {
    $result = Invoke-VisibleWordRoundTrip -SourcePath $sourcePath -Workspace $workspace
    Copy-NewFile -Source $result.output_docx -Destination (Join-Path $handoff "output.docx")
    Copy-NewFile -Source $result.reference_pdf -Destination (Join-Path $handoff "reference.pdf")
    Copy-NewFile -Source $result.candidate_pdf -Destination (Join-Path $handoff "candidate.pdf")
    $receipt = [ordered]@{
        schema_version = "genoffice_docx_word_interactive_receipt.v1"
        assignment_id = [string]$request.assignment_id
        run_request_hash = [string]$request.request_hash
        host_readiness_report_sha256 = [string]$request.host_readiness_report_sha256
        runner_script_sha256 = [string]$request.runner_script_sha256
        operator_account_sid_sha256 = [string]$request.operator_account_sid_sha256
        word_executable_sha256 = [string]$request.word_executable_sha256
        network_isolation_rule_sha256 = [string]$request.network_isolation_rule_sha256
        source_content_sha256 = [string]$request.source_content_sha256
        output_docx_sha256 = Get-Sha256File -Path (Join-Path $handoff "output.docx")
        reference_pdf_sha256 = Get-Sha256File -Path (Join-Path $handoff "reference.pdf")
        candidate_pdf_sha256 = Get-Sha256File -Path (Join-Path $handoff "candidate.pdf")
        word_version = [string]$observedHost.word_version
        windows_product_name = [string]$observedHost.windows_product_name
        windows_display_version = [string]$observedHost.windows_display_version
        windows_build = [string]$observedHost.windows_build
        process_architecture = [string]$observedHost.process_architecture
        powershell_version = [string]$observedHost.powershell_version
        font_inventory = @($observedHost.font_inventory)
        font_count = [int]$observedHost.font_count
        normalized_font_inventory_sha256 = [string]$observedHost.normalized_font_inventory_sha256
        started_at_utc = [string]$result.started_at_utc
        human_confirmed_at_utc = [string]$result.human_confirmed_at_utc
        completed_at_utc = [string]$result.completed_at_utc
        engine_id = "microsoft_word"
        runner_mode = "interactive_windows_client"
        interactive_user_session_verified = $true
        session_zero_absent = $true
        dedicated_local_account_verified = $true
        word_visible_during_execution = $true
        explicit_human_confirmation_verified = $true
        macros_force_disabled = $true
        source_opened_read_only = $true
        add_to_recent_files = $false
        network_isolation_verified = $true
        office_identity_absent = $true
        tenant_credentials_available = $false
        signing_custody_accessible = $false
        source_synthetic = $true
        tenant_content_processed = $false
        persistent_product_version_written = $false
        private_key_included = $false
        document_content_in_receipt = $false
    }
    Write-NewUtf8Json -Path (Join-Path $handoff "word-interactive-receipt.json") -Value $receipt
    Write-Output (ConvertTo-Json -InputObject $receipt -Depth 8 -Compress)
}
finally {
    if ($workspace.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()), [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $workspace -PathType Container)) {
        Remove-Item -LiteralPath $workspace -Recurse -Force
    }
}
