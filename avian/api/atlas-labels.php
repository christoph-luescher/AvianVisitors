<?php
// AvianVisitors - selected Atlas species-name translations.
// Returns labels for ATLAS_LANGUAGE_1/2/3 as configured in birdnet.conf.

declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$BIRDNETPI_DIR = dirname(__DIR__, 2);
$CONF_PATH = "$BIRDNETPI_DIR/birdnet.conf";
$L18N_DIR = "$BIRDNETPI_DIR/model/l18n";

function read_conf(string $path): array {
    if (!is_readable($path)) return [];
    $out = [];
    foreach (file($path, FILE_IGNORE_NEW_LINES) as $line) {
        if (!$line || $line[0] === '#') continue;
        if (preg_match('/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$/i', $line, $m)) {
            $val = trim($m[2]);
            if (strlen($val) >= 2 && $val[0] === '"' && substr($val, -1) === '"') {
                $val = substr($val, 1, -1);
            }
            $out[$m[1]] = $val;
        }
    }
    return $out;
}

function language_names(): array {
    return [
        'af' => 'Afrikaans',
        'ar' => 'Arabic',
        'bg' => 'Bulgarian',
        'ca' => 'Catalan',
        'cs' => 'Czech',
        'da' => 'Danish',
        'de' => 'German',
        'en' => 'English',
        'es' => 'Spanish',
        'et' => 'Estonian',
        'fi' => 'Finnish',
        'fr' => 'French',
        'hr' => 'Croatian',
        'hu' => 'Hungarian',
        'id' => 'Indonesian',
        'is' => 'Icelandic',
        'it' => 'Italian',
        'ja' => 'Japanese',
        'ko' => 'Korean',
        'lt' => 'Lithuanian',
        'lv' => 'Latvian',
        'nl' => 'Dutch',
        'no' => 'Norwegian',
        'pl' => 'Polish',
        'pt' => 'Portuguese',
        'ro' => 'Romanian',
        'ru' => 'Russian',
        'sk' => 'Slovak',
        'sl' => 'Slovenian',
        'sr' => 'Serbian',
        'sv' => 'Swedish',
        'th' => 'Thai',
        'tr' => 'Turkish',
        'uk' => 'Ukrainian',
        'vi' => 'Vietnamese',
        'zh_CN' => 'Chinese (Simplified)',
        'zh_TW' => 'Chinese (Traditional)',
    ];
}

$conf = read_conf($CONF_PATH);
$available = [];
foreach (glob($L18N_DIR . '/labels_*.json') ?: [] as $file) {
    $code = preg_replace('/^labels_|\.json$/', '', basename($file));
    if ($code !== '') $available[$code] = $file;
}

$defaultLanguage = isset($available[$conf['DATABASE_LANG'] ?? ''])
    ? $conf['DATABASE_LANG']
    : (isset($available['en']) ? 'en' : array_key_first($available));

$selected = [
    $conf['ATLAS_LANGUAGE_1'] ?? $defaultLanguage,
    $conf['ATLAS_LANGUAGE_2'] ?? 'none',
    $conf['ATLAS_LANGUAGE_3'] ?? 'none',
];

$names = language_names();
$languages = [];
$labels = [];
foreach ($selected as $code) {
    if ($code === 'none' || !isset($available[$code]) || isset($labels[$code])) continue;
    $raw = file_get_contents($available[$code]);
    $decoded = json_decode((string)$raw, true);
    if (!is_array($decoded)) continue;
    $languages[] = ['code' => $code, 'label' => $names[$code] ?? $code];
    $labels[$code] = $decoded;
}

echo json_encode([
    'languages' => $languages,
    'labels' => $labels,
]);
