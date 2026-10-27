using System.Reflection;
using System.Text.Json;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Validation;

if (args.Length != 1 || string.IsNullOrWhiteSpace(args[0]))
{
    return 2;
}

var assembly = typeof(WordprocessingDocument).Assembly;
var packageVersion = assembly
    .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?
    .InformationalVersion
    ?? assembly.GetName().Version?.ToString()
    ?? "unknown";
if (args[0] == "--version")
{
    WriteReport(packageVersion, Array.Empty<object>());
    return 0;
}

var inputPath = Path.GetFullPath(args[0]);
if (!File.Exists(inputPath))
{
    return 2;
}

var openSettings = new OpenSettings
{
    AutoSave = false,
    MarkupCompatibilityProcessSettings = new MarkupCompatibilityProcessSettings(
        MarkupCompatibilityProcessMode.ProcessAllParts,
        FileFormatVersions.Office2021
    ),
};

using var document = WordprocessingDocument.Open(inputPath, false, openSettings);
var validator = new OpenXmlValidator(FileFormatVersions.Office2021);
var findings = validator.Validate(document)
    .Select(error => new
    {
        error_id = string.IsNullOrWhiteSpace(error.Id) ? "OpenXmlValidationError" : error.Id,
        error_type = NormalizeErrorType(error.ErrorType.ToString()),
        part_uri = error.Part?.Uri.ToString() ?? "/",
        path = error.Path?.XPath ?? "/",
    })
    .OrderBy(item => item.part_uri, StringComparer.Ordinal)
    .ThenBy(item => item.error_type, StringComparer.Ordinal)
    .ThenBy(item => item.error_id, StringComparer.Ordinal)
    .ThenBy(item => item.path, StringComparer.Ordinal)
    .ToArray();

WriteReport(packageVersion, findings);
return 0;

static void WriteReport(string packageVersion, object findings)
{
var report = new
{
    validator_name = "DocumentFormat.OpenXml",
    validator_version = packageVersion,
    target_file_format_version = "Office2021",
    markup_compatibility_processing_enabled = true,
    findings,
};
Console.WriteLine(JsonSerializer.Serialize(report));
}

static string NormalizeErrorType(string errorType) => errorType switch
{
    "Schema" => "schema",
    "Semantic" => "semantic",
    "Package" => "package",
    "MarkupCompatibility" => "markup_compatibility",
    _ => throw new InvalidOperationException($"Unsupported Open XML validation error type: {errorType}"),
};
