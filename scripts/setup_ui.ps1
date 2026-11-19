<#
Jarvis setup window (0.4.2l): the visual face of Update.bat and install_windows.bat.

It only SHOWS progress. The work is done by Update.py / install_windows.ps1, which
append JSON lines to -Events:
  {"t":"plan","mode":"update","version":"0.4.2l","steps":[{"id":"check","w":3},...]}
  {"t":"step","id":"libs","state":"active|done|skip|warn|fail","note":"..."}
  {"t":"detail","text":"..."}        what is happening right now
  {"t":"log","text":"..."}           a line for «Подробнее»
  {"t":"bytes","done":N,"total":M}   download progress of the current step
  {"t":"done","ok":true,"message":"..."}
The internet speed is measured here from the network adapters, so it is the real
speed of whatever is downloading (archive, pip packages, models).
Built-in WPF: works before Python exists (first install). Theme, accent, font and
language come from config.json when it exists.
#>
param(
    [Parameter(Mandatory = $true)][string]$Events,
    [string]$Mode = 'update',
    [string]$Root = '',
    [int]$ProducerPid = 0,
    [string]$Ready = ''
)

if (-not $Root) { $Root = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent }
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Xaml

# ---------------------------------------------------------------- settings
$cfg = $null
try {
    $cfgPath = Join-Path $Root 'config.json'
    if (Test-Path -LiteralPath $cfgPath) { $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json }
} catch { $cfg = $null }
function Get-Setting([string]$Name, $Default) {
    if ($null -ne $cfg -and $cfg.PSObject.Properties.Name -contains $Name -and $cfg.$Name) { return $cfg.$Name }
    return $Default
}
$accent = [string](Get-Setting 'ui_accent' '#3978f6')
if ($accent -notmatch '^#[0-9a-fA-F]{6}$') { $accent = '#3978f6' }
$theme = [string](Get-Setting 'ui_theme' 'dark')
$language = [string](Get-Setting 'ui_language' '')
if (-not $language) {
    $culture = [Globalization.CultureInfo]::CurrentUICulture.TwoLetterISOLanguageName
    $language = if ($culture -in @('ru', 'uk', 'be')) { 'ru' } elseif ($culture -eq 'ro') { 'ro' } else { 'en' }
}
if ($language -notin @('ru', 'ro', 'en')) { $language = 'en' }
$fontChoice = [string](Get-Setting 'ui_font_family' 'Onest')

function ConvertTo-Rgb([string]$Hex) {
    return @([Convert]::ToInt32($Hex.Substring(1, 2), 16), [Convert]::ToInt32($Hex.Substring(3, 2), 16), [Convert]::ToInt32($Hex.Substring(5, 2), 16))
}
function Join-Color([string]$A, [string]$B, [double]$T) {
    $x = ConvertTo-Rgb $A; $y = ConvertTo-Rgb $B
    $c = 0..2 | ForEach-Object { [int][Math]::Round($x[$_] + ($y[$_] - $x[$_]) * $T) }
    return ('#{0:x2}{1:x2}{2:x2}' -f $c[0], $c[1], $c[2])
}

if ($theme -eq 'light') {
    $P = @{ bg = '#f5f7fb'; surface = '#ffffff'; control = '#edf1f7'; border = '#cdd6e4'; text = '#1c2738'; muted = '#667184' }
} else {
    $P = @{ bg = '#0b0d11'; surface = '#16181c'; control = '#22252a'; border = '#2c3036'; text = '#f0f2f6'; muted = '#9aa1ad' }
    $bgSetting = [string](Get-Setting 'ui_background' '')
    if ($bgSetting -match '^#[0-9a-fA-F]{6}$') { $P.bg = $bgSetting; $P.surface = Join-Color $bgSetting '#ffffff' 0.07 }
}
$P.accent = $accent
$P.accentLight = Join-Color $accent '#ffffff' 0.30
$P.accentDark = Join-Color $accent '#000000' 0.28
$P.accentSoft = Join-Color $P.surface $accent 0.16
$P.track = Join-Color $P.surface $P.text 0.10
$P.good = '#32b87a'; $P.warn = '#e0a43a'; $P.bad = '#e5484d'

# Fonts of the app (Fuzzy Bubbles + Pangolin for Cyrillic, or Onest), with Segoe UI behind.
$fontDirs = @((Join-Path $Root 'assets\fonts'), (Join-Path $Root 'luxai\assets\fonts'))
# WPF keeps a font file open while it is shown, so the update could not replace luxai\assets\fonts\Onest.ttf
# («Access is denied»). Each font is copied to a private temporary folder and used from there.
$fontCache = Join-Path ([IO.Path]::GetTempPath()) ("luxai_setup_fonts_" + $PID)
function Get-FontUri([string]$File, [string]$Family) {
    foreach ($dir in $fontDirs) {
        $path = Join-Path $dir $File
        if (Test-Path -LiteralPath $path) {
            try {
                $own = Join-Path $fontCache ([IO.Path]::GetFileNameWithoutExtension($File))
                New-Item -ItemType Directory -Path $own -Force | Out-Null
                Copy-Item -LiteralPath $path -Destination (Join-Path $own $File) -Force
                return ((New-Object Uri ($own.TrimEnd('\') + '\')).AbsoluteUri + '#' + $Family)
            } catch {
                return $null  # no copy, no project font: the window falls back to Segoe UI
            }
        }
    }
    return $null
}
$families = @()
if ($fontChoice -eq 'Fuzzy Bubbles') {
    $families += (Get-FontUri 'FuzzyBubbles-Regular.ttf' 'Fuzzy Bubbles')
    $families += (Get-FontUri 'Pangolin-Regular.ttf' 'Pangolin')
}
if ($fontChoice -ne 'system') { $families += (Get-FontUri 'Onest.ttf' 'Onest') }
$families = @($families | Where-Object { $_ }) + @('Segoe UI Variable Text', 'Segoe UI')
$fontFamily = $families -join ', '

# ---------------------------------------------------------------- texts
$T = @{
    ru = @{
        update = 'Обновление Jarvis'; install = 'Установка Jarvis'; preparing = 'Готовлю…'; version = 'Версия {0}'
        speed = 'Скорость интернета'; downloaded = 'Скачано'; elapsed = 'Прошло'; left = 'Осталось ≈ {0}'
        details = 'Подробнее'; hide = 'Скрыть'; launch = 'Запустить Jarvis'; close = 'Закрыть'; log = 'Открыть журнал'
        doneUpdate = 'Готово — Jarvis обновлён'; doneInstall = 'Готово — Jarvis установлен'; failed = 'Не получилось'
        stopped = 'Установщик неожиданно остановился. Подробности — в журнале.'; closesIn = 'Окно закроется через {0} с'
        upToDate = 'Jarvis уже последней версии — проверил библиотеки и модели.'; skipped = 'не нужно'; warn = 'с предупреждением'
        steps = @{ check = 'Проверяю новую версию'; download = 'Скачиваю обновление'; apply = 'Устанавливаю файлы'
            libs = 'Обновляю библиотеки'; gguf = 'Проверяю локальный ИИ'; ocr = 'Готовлю распознавание текста'
            translator = 'Офлайн-переводчик'; cleanup = 'Убираю старые файлы'; python = 'Ищу Python'
            venv = 'Готовлю окружение'; verify = 'Проверяю приложение' }
    }
    ro = @{
        update = 'Actualizare Jarvis'; install = 'Instalare Jarvis'; preparing = 'Pregătesc…'; version = 'Versiunea {0}'
        speed = 'Viteza internetului'; downloaded = 'Descărcat'; elapsed = 'Timp scurs'; left = 'Mai durează ≈ {0}'
        details = 'Detalii'; hide = 'Ascunde'; launch = 'Pornește Jarvis'; close = 'Închide'; log = 'Deschide jurnalul'
        doneUpdate = 'Gata — Jarvis e actualizat'; doneInstall = 'Gata — Jarvis e instalat'; failed = 'Nu a reușit'
        stopped = 'Instalarea s-a oprit neașteptat. Detaliile sunt în jurnal.'; closesIn = 'Fereastra se închide în {0} s'
        upToDate = 'Jarvis e deja la ultima versiune — am verificat bibliotecile și modelele.'; skipped = 'nu e nevoie'; warn = 'cu avertisment'
        steps = @{ check = 'Verific versiunea nouă'; download = 'Descarc actualizarea'; apply = 'Instalez fișierele'
            libs = 'Actualizez bibliotecile'; gguf = 'Verific AI-ul local'; ocr = 'Pregătesc recunoașterea textului'
            translator = 'Traducătorul offline'; cleanup = 'Curăț fișierele vechi'; python = 'Caut Python'
            venv = 'Pregătesc mediul'; verify = 'Verific aplicația' }
    }
    en = @{
        update = 'Jarvis update'; install = 'Jarvis setup'; preparing = 'Preparing…'; version = 'Version {0}'
        speed = 'Internet speed'; downloaded = 'Downloaded'; elapsed = 'Elapsed'; left = '≈ {0} left'
        details = 'Details'; hide = 'Hide'; launch = 'Launch Jarvis'; close = 'Close'; log = 'Open log'
        doneUpdate = 'Done — Jarvis is up to date'; doneInstall = 'Done — Jarvis is installed'; failed = 'It did not work'
        stopped = 'Setup stopped unexpectedly. Details are in the log.'; closesIn = 'Closing in {0} s'
        upToDate = 'Jarvis is already the latest version — libraries and models checked.'; skipped = 'not needed'; warn = 'with a warning'
        steps = @{ check = 'Checking for a new version'; download = 'Downloading the update'; apply = 'Installing files'
            libs = 'Updating libraries'; gguf = 'Checking the local AI'; ocr = 'Preparing text recognition'
            translator = 'Offline translator'; cleanup = 'Cleaning up'; python = 'Finding Python'
            venv = 'Preparing the environment'; verify = 'Checking the app' }
    }
}
$L = $T[$language]
$title = if ($Mode -eq 'install') { $L.install } else { $L.update }

# ---------------------------------------------------------------- logo
$logoData = 'M16 8 L48 8 L48 20 L38 20 L38 44 Q38 56 26 56 L16 56 L16 44 L24 44 Q26 44 26 42 L26 20 L16 20 Z'
$logoTransform = 'Identity'
try {
    $svg = Get-Content -LiteralPath (Join-Path $Root 'luxai\assets\icons\jarvis.svg') -Raw -Encoding UTF8
    $match = [regex]::Match($svg, '<path[^>]*transform="translate\(([\d.]+) ([\d.]+)\) scale\(([\d.]+)\)"[^>]*d="([^"]+)"')
    if ($match.Success) {
        $logoData = 'F1 ' + $match.Groups[4].Value
        $s = $match.Groups[3].Value; $logoTransform = "$s,0,0,$s,$($match.Groups[1].Value),$($match.Groups[2].Value)"
    }
} catch { }

# ---------------------------------------------------------------- window
$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="$title" Width="620" SizeToContent="Height" WindowStartupLocation="CenterScreen"
        WindowStyle="None" AllowsTransparency="True" Background="Transparent" ResizeMode="CanMinimize"
        FontFamily="$fontFamily" FontSize="13.5" Foreground="$($P.text)" UseLayoutRounding="True"
        TextOptions.TextFormattingMode="Ideal" ShowInTaskbar="True" Topmost="False">
  <Window.Resources>
    <Style x:Key="Chrome" TargetType="Button">
      <Setter Property="Foreground" Value="$($P.muted)"/><Setter Property="Width" Value="34"/><Setter Property="Height" Value="30"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template"><Setter.Value><ControlTemplate TargetType="Button">
        <Border x:Name="b" CornerRadius="8" Background="Transparent"><ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/></Border>
        <ControlTemplate.Triggers><Trigger Property="IsMouseOver" Value="True"><Setter TargetName="b" Property="Background" Value="$($P.control)"/></Trigger></ControlTemplate.Triggers>
      </ControlTemplate></Setter.Value></Setter>
    </Style>
    <Style x:Key="Primary" TargetType="Button">
      <Setter Property="Foreground" Value="White"/><Setter Property="FontSize" Value="14"/><Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Cursor" Value="Hand"/><Setter Property="Padding" Value="20,10"/>
      <Setter Property="Template"><Setter.Value><ControlTemplate TargetType="Button">
        <Border x:Name="b" CornerRadius="12" Padding="{TemplateBinding Padding}">
          <Border.Background><LinearGradientBrush StartPoint="0,0" EndPoint="1,1"><GradientStop Color="$($P.accentLight)" Offset="0"/><GradientStop Color="$($P.accent)" Offset="0.55"/><GradientStop Color="$($P.accentDark)" Offset="1"/></LinearGradientBrush></Border.Background>
          <ContentPresenter HorizontalAlignment="Center"/></Border>
        <ControlTemplate.Triggers><Trigger Property="IsMouseOver" Value="True"><Setter TargetName="b" Property="Opacity" Value="0.88"/></Trigger></ControlTemplate.Triggers>
      </ControlTemplate></Setter.Value></Setter>
    </Style>
    <Style x:Key="Secondary" TargetType="Button">
      <Setter Property="Foreground" Value="$($P.text)"/><Setter Property="FontSize" Value="14"/><Setter Property="Cursor" Value="Hand"/><Setter Property="Padding" Value="18,10"/>
      <Setter Property="Template"><Setter.Value><ControlTemplate TargetType="Button">
        <Border x:Name="b" CornerRadius="12" Padding="{TemplateBinding Padding}" Background="$($P.control)" BorderBrush="$($P.border)" BorderThickness="1"><ContentPresenter HorizontalAlignment="Center"/></Border>
        <ControlTemplate.Triggers><Trigger Property="IsMouseOver" Value="True"><Setter TargetName="b" Property="BorderBrush" Value="$($P.accent)"/></Trigger></ControlTemplate.Triggers>
      </ControlTemplate></Setter.Value></Setter>
    </Style>
    <Style x:Key="Link" TargetType="Button">
      <Setter Property="Foreground" Value="$($P.muted)"/><Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template"><Setter.Value><ControlTemplate TargetType="Button">
        <ContentPresenter/>
      </ControlTemplate></Setter.Value></Setter>
    </Style>
  </Window.Resources>
  <Border Margin="18" CornerRadius="18" Background="$($P.surface)" BorderBrush="$($P.border)" BorderThickness="1" x:Name="Card">
    <Border.Effect><DropShadowEffect BlurRadius="26" ShadowDepth="6" Opacity="0.45" Color="#000000"/></Border.Effect>
    <Grid>
      <!-- soft accent glow at the top, like a Discord / Fluent splash -->
      <Border CornerRadius="18,18,0,0" Height="150" VerticalAlignment="Top" IsHitTestVisible="False">
        <Border.Background><RadialGradientBrush Center="0.18,0" GradientOrigin="0.18,0" RadiusX="0.9" RadiusY="1.2">
          <GradientStop Color="$($P.accent)" Offset="0"/><GradientStop Color="#00000000" Offset="1"/></RadialGradientBrush></Border.Background>
        <Border.OpacityMask><LinearGradientBrush StartPoint="0,0" EndPoint="0,1"><GradientStop Color="#40000000" Offset="0"/><GradientStop Color="#00000000" Offset="1"/></LinearGradientBrush></Border.OpacityMask>
      </Border>
      <StackPanel Margin="26,20,26,24">
        <!-- header -->
        <Grid x:Name="Header" Background="Transparent">
          <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
          <Grid Width="52" Height="52" x:Name="LogoBox">
            <Border CornerRadius="15">
              <Border.Background><LinearGradientBrush StartPoint="0,0" EndPoint="1,1"><GradientStop Color="$($P.accentLight)" Offset="0"/><GradientStop Color="$($P.accent)" Offset="0.5"/><GradientStop Color="$($P.accentDark)" Offset="1"/></LinearGradientBrush></Border.Background>
            </Border>
            <Border CornerRadius="15" BorderBrush="#38FFFFFF" BorderThickness="1"/>
            <!-- the app icon is drawn on a 64 px grid with the tile at 2..62: same proportions here -->
            <Viewbox Margin="-1.7"><Canvas Width="64" Height="64"><Path Fill="White" Data="$logoData" RenderTransform="$logoTransform"/></Canvas></Viewbox>
            <Rectangle x:Name="Pulse" Width="52" Height="52" RadiusX="15" RadiusY="15" Stroke="$($P.accent)" StrokeThickness="2" Opacity="0" RenderTransformOrigin="0.5,0.5">
              <Rectangle.RenderTransform><ScaleTransform x:Name="PulseScale"/></Rectangle.RenderTransform>
            </Rectangle>
          </Grid>
          <StackPanel Grid.Column="1" Margin="16,2,0,0" VerticalAlignment="Center">
            <TextBlock Text="$title" FontSize="21" FontWeight="SemiBold"/>
            <TextBlock x:Name="Subtitle" Text="Jarvis" Foreground="$($P.muted)" Margin="0,2,0,0"/>
          </StackPanel>
          <StackPanel Grid.Column="2" Orientation="Horizontal" VerticalAlignment="Top">
            <Button x:Name="MinButton" Style="{StaticResource Chrome}"><Path Data="M0,0 L10,0" Stroke="$($P.muted)" StrokeThickness="1.4" Margin="0,6,0,0"/></Button>
            <Button x:Name="CloseButton" Style="{StaticResource Chrome}" Visibility="Collapsed"><Path Data="M0,0 L10,10 M10,0 L0,10" Stroke="$($P.muted)" StrokeThickness="1.4"/></Button>
          </StackPanel>
        </Grid>

        <!-- what is happening now -->
        <TextBlock x:Name="StepTitle" Text="$($L.preparing)" FontSize="17" FontWeight="SemiBold" Margin="0,24,0,0" TextTrimming="CharacterEllipsis"/>
        <TextBlock x:Name="StepDetail" Text=" " Foreground="$($P.muted)" Margin="0,4,0,0" TextTrimming="CharacterEllipsis"/>

        <!-- overall progress -->
        <Grid Margin="0,14,0,0" Height="8">
          <Border CornerRadius="4" Background="$($P.track)"/>
          <Border x:Name="Bar" CornerRadius="4" HorizontalAlignment="Left" Width="0">
            <Border.Background><LinearGradientBrush StartPoint="0,0" EndPoint="1,0"><GradientStop Color="$($P.accent)" Offset="0"/><GradientStop Color="$($P.accentLight)" Offset="1"/></LinearGradientBrush></Border.Background>
          </Border>
          <Border x:Name="Shine" CornerRadius="4" HorizontalAlignment="Left" Width="70" Opacity="0.0">
            <Border.Background><LinearGradientBrush StartPoint="0,0" EndPoint="1,0"><GradientStop Color="#00FFFFFF" Offset="0"/><GradientStop Color="#66FFFFFF" Offset="0.5"/><GradientStop Color="#00FFFFFF" Offset="1"/></LinearGradientBrush></Border.Background>
            <Border.RenderTransform><TranslateTransform x:Name="ShineMove"/></Border.RenderTransform>
          </Border>
        </Grid>
        <Grid Margin="0,8,0,0">
          <TextBlock x:Name="Percent" Text="0%" FontWeight="SemiBold"/>
          <TextBlock x:Name="Eta" Text=" " Foreground="$($P.muted)" HorizontalAlignment="Right"/>
        </Grid>

        <!-- numbers, like Steam's download page -->
        <Grid Margin="0,16,0,0">
          <Grid.ColumnDefinitions><ColumnDefinition Width="1.5*"/><ColumnDefinition Width="12"/><ColumnDefinition Width="*"/><ColumnDefinition Width="12"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
          <Border CornerRadius="14" Background="$($P.control)" Padding="14,10">
            <Grid>
              <StackPanel>
                <TextBlock Text="$($L.speed)" Foreground="$($P.muted)" FontSize="12"/>
                <TextBlock x:Name="Speed" Text="—" FontSize="18" FontWeight="SemiBold" Margin="0,2,0,0"/>
                <TextBlock x:Name="SpeedBits" Text=" " Foreground="$($P.muted)" FontSize="11.5"/>
              </StackPanel>
              <Canvas x:Name="Graph" Width="96" Height="40" HorizontalAlignment="Right" VerticalAlignment="Center" ClipToBounds="True">
                <Polygon x:Name="GraphFill" Fill="$($P.accentSoft)"/>
                <Polyline x:Name="GraphLine" Stroke="$($P.accent)" StrokeThickness="1.8" StrokeLineJoin="Round"/>
              </Canvas>
            </Grid>
          </Border>
          <Border Grid.Column="2" CornerRadius="14" Background="$($P.control)" Padding="14,10">
            <StackPanel>
              <TextBlock Text="$($L.downloaded)" Foreground="$($P.muted)" FontSize="12"/>
              <TextBlock x:Name="Downloaded" Text="0 MB" FontSize="18" FontWeight="SemiBold" Margin="0,2,0,0"/>
              <TextBlock x:Name="StepBytes" Text=" " Foreground="$($P.muted)" FontSize="11.5" TextTrimming="CharacterEllipsis"/>
            </StackPanel>
          </Border>
          <Border Grid.Column="4" CornerRadius="14" Background="$($P.control)" Padding="14,10">
            <StackPanel>
              <TextBlock Text="$($L.elapsed)" Foreground="$($P.muted)" FontSize="12"/>
              <TextBlock x:Name="Elapsed" Text="0:00" FontSize="18" FontWeight="SemiBold" Margin="0,2,0,0"/>
            </StackPanel>
          </Border>
        </Grid>

        <!-- steps, like the Visual Studio Installer checklist -->
        <StackPanel x:Name="Steps" Margin="2,18,0,0"/>

        <!-- result -->
        <Border x:Name="Result" CornerRadius="14" Padding="16,12" Margin="0,16,0,0" Visibility="Collapsed">
          <StackPanel>
            <TextBlock x:Name="ResultTitle" FontSize="16" FontWeight="SemiBold"/>
            <TextBlock x:Name="ResultText" Foreground="$($P.muted)" TextWrapping="Wrap" Margin="0,3,0,0"/>
          </StackPanel>
        </Border>

        <!-- footer -->
        <Grid Margin="0,18,0,0">
          <Button x:Name="DetailsButton" Style="{StaticResource Link}" VerticalAlignment="Center" HorizontalAlignment="Left">
            <StackPanel Orientation="Horizontal">
              <Path x:Name="Chevron" Data="M0,0 L4,4 L8,0" Stroke="$($P.muted)" StrokeThickness="1.5" VerticalAlignment="Center" Margin="0,2,8,0" RenderTransformOrigin="0.5,0.5">
                <Path.RenderTransform><RotateTransform x:Name="ChevronTurn" Angle="-90"/></Path.RenderTransform></Path>
              <TextBlock x:Name="DetailsText" Text="$($L.details)"/>
            </StackPanel>
          </Button>
          <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
            <TextBlock x:Name="Countdown" Foreground="$($P.muted)" VerticalAlignment="Center" Margin="0,0,14,0" FontSize="12"/>
            <Button x:Name="LogButton" Style="{StaticResource Secondary}" Content="$($L.log)" Margin="0,0,10,0" Visibility="Collapsed"/>
            <Button x:Name="FinishButton" Style="{StaticResource Secondary}" Content="$($L.close)" Margin="0,0,10,0" Visibility="Collapsed"/>
            <Button x:Name="LaunchButton" Style="{StaticResource Primary}" Content="$($L.launch)" Visibility="Collapsed"/>
          </StackPanel>
        </Grid>
        <Border x:Name="LogBox" CornerRadius="12" Background="$($P.bg)" BorderBrush="$($P.border)" BorderThickness="1" Margin="0,12,0,0" Visibility="Collapsed">
          <TextBox x:Name="LogText" Height="170" IsReadOnly="True" Background="Transparent" BorderThickness="0" Padding="10,8"
                   Foreground="$($P.muted)" FontFamily="Cascadia Mono, Consolas" FontSize="11.5" TextWrapping="Wrap"
                   VerticalScrollBarVisibility="Auto"/>
        </Border>
      </StackPanel>
    </Grid>
  </Border>
</Window>
"@

$window = [Windows.Markup.XamlReader]::Parse($xaml)
$ui = @{}
foreach ($name in 'Card', 'Header', 'Subtitle', 'MinButton', 'CloseButton', 'StepTitle', 'StepDetail', 'Bar', 'Shine', 'ShineMove',
    'Percent', 'Eta', 'Speed', 'SpeedBits', 'Graph', 'GraphFill', 'GraphLine', 'Downloaded', 'StepBytes', 'Elapsed', 'Steps',
    'Result', 'ResultTitle', 'ResultText', 'DetailsButton', 'DetailsText', 'ChevronTurn', 'Countdown', 'LogButton',
    'FinishButton', 'LaunchButton', 'LogBox', 'LogText', 'Pulse', 'PulseScale') {
    $ui[$name] = $window.FindName($name)
}
$brush = { param($hex) New-Object Windows.Media.SolidColorBrush ([Windows.Media.ColorConverter]::ConvertFromString($hex)) }

# Taskbar icon: the same logo tile, rendered once.
try {
    $logoBox = $window.FindName('LogoBox')
    $window.Add_ContentRendered({
            try {
                $bmp = New-Object Windows.Media.Imaging.RenderTargetBitmap 52, 52, 96, 96, ([Windows.Media.PixelFormats]::Pbgra32)
                $bmp.Render($logoBox); $window.Icon = $bmp
            } catch { }
        })
} catch { }

# ---------------------------------------------------------------- state
$state = @{
    steps = [ordered]@{}; current = $null; started = [DateTime]::Now; stepStarted = [DateTime]::Now
    bytesDone = 0.0; bytesTotal = 0.0; finished = $false; ok = $false; shownProgress = 0.0
    lastRx = -1.0; lastRxAt = [DateTime]::Now; speed = 0.0; downloaded = 0.0; samples = New-Object System.Collections.ArrayList
    position = 0L; log = New-Object System.Text.StringBuilder; countdown = -1; plannedOnce = $false
}

function Get-ReceivedBytes {
    $sum = 0.0
    foreach ($nic in [Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
        if ($nic.OperationalStatus -ne 'Up' -or $nic.NetworkInterfaceType -eq 'Loopback' -or $nic.NetworkInterfaceType -eq 'Tunnel') { continue }
        try { $sum += $nic.GetIPStatistics().BytesReceived } catch { }
    }
    return $sum
}
function Format-Bytes([double]$Value) {
    if ($Value -ge 1GB) { return ('{0:0.00} GB' -f ($Value / 1GB)) }
    if ($Value -ge 100MB) { return ('{0:0} MB' -f ($Value / 1MB)) }
    if ($Value -ge 1MB) { return ('{0:0.0} MB' -f ($Value / 1MB)) }
    return ('{0:0} KB' -f ($Value / 1KB))
}
function Format-Time([double]$Seconds) {
    $s = [Math]::Max(0, [int][Math]::Round($Seconds))
    if ($s -ge 3600) { return ('{0}:{1:00}:{2:00}' -f [int]($s / 3600), [int](($s % 3600) / 60), ($s % 60)) }
    return ('{0}:{1:00}' -f [int]($s / 60), ($s % 60))
}
function Format-Left([double]$Seconds) {
    $s = [Math]::Max(1, [int][Math]::Ceiling($Seconds))
    $min = @{ ru = 'мин'; ro = 'min'; en = 'min' }[$language]; $sec = @{ ru = 'с'; ro = 's'; en = 's' }[$language]
    $value = if ($s -ge 60) { '{0} {1} {2} {3}' -f [int]($s / 60), $min, ($s % 60), $sec } else { '{0} {1}' -f $s, $sec }
    return ($L.left -f $value)
}

function New-StepRow([string]$Id) {
    $row = New-Object Windows.Controls.Grid
    $row.Margin = '0,4,0,4'
    $c0 = New-Object Windows.Controls.ColumnDefinition; $c0.Width = '26'
    $c1 = New-Object Windows.Controls.ColumnDefinition; $c1.Width = '*'
    $c2 = New-Object Windows.Controls.ColumnDefinition; $c2.Width = 'Auto'
    [void]$row.ColumnDefinitions.Add($c0); [void]$row.ColumnDefinitions.Add($c1); [void]$row.ColumnDefinitions.Add($c2)
    $icon = New-Object Windows.Controls.Grid; $icon.Width = 16; $icon.Height = 16; $icon.HorizontalAlignment = 'Left'
    $ring = New-Object Windows.Shapes.Ellipse; $ring.Stroke = (& $brush $P.border); $ring.StrokeThickness = 1.6
    $arc = New-Object Windows.Shapes.Path; $arc.Stroke = (& $brush $P.accent); $arc.StrokeThickness = 2.2
    $arc.StrokeStartLineCap = 'Round'; $arc.StrokeEndLineCap = 'Round'
    $arc.Data = [Windows.Media.Geometry]::Parse('M8,0.8 A7.2,7.2 0 0 1 15.2,8'); $arc.Visibility = 'Collapsed'
    $arc.RenderTransformOrigin = '0.5,0.5'; $spin = New-Object Windows.Media.RotateTransform; $arc.RenderTransform = $spin
    $mark = New-Object Windows.Shapes.Path; $mark.StrokeThickness = 1.9; $mark.Stroke = (& $brush '#ffffff')
    $mark.StrokeStartLineCap = 'Round'; $mark.StrokeEndLineCap = 'Round'; $mark.Visibility = 'Collapsed'
    $mark.Stretch = 'None'; $mark.HorizontalAlignment = 'Center'; $mark.VerticalAlignment = 'Center'
    [void]$icon.Children.Add($ring); [void]$icon.Children.Add($arc); [void]$icon.Children.Add($mark)
    $text = New-Object Windows.Controls.TextBlock; $text.Text = $L.steps[$Id]; if (-not $text.Text) { $text.Text = $Id }
    $text.Foreground = (& $brush $P.muted); [Windows.Controls.Grid]::SetColumn($text, 1)
    $note = New-Object Windows.Controls.TextBlock; $note.Foreground = (& $brush $P.muted); $note.FontSize = 12
    $note.VerticalAlignment = 'Center'; [Windows.Controls.Grid]::SetColumn($note, 2)
    [void]$row.Children.Add($icon); [void]$row.Children.Add($text); [void]$row.Children.Add($note)
    [void]$ui.Steps.Children.Add($row)
    $animation = New-Object Windows.Media.Animation.DoubleAnimation 0, 360, ([TimeSpan]::FromSeconds(0.9))
    $animation.RepeatBehavior = [Windows.Media.Animation.RepeatBehavior]::Forever
    return @{ row = $row; ring = $ring; arc = $arc; spin = $spin; anim = $animation; mark = $mark; text = $text; note = $note
        state = 'pending'; weight = 5.0; started = $null; took = 0.0 }
}

function Set-StepState([string]$Id, [string]$StepState, [string]$Note = '') {
    if (-not $state.steps.Contains($Id)) { $state.steps[$Id] = New-StepRow $Id }
    $s = $state.steps[$Id]
    $now = [DateTime]::Now
    if ($StepState -eq 'active') {
        if ($state.current -and $state.current -ne $Id -and $state.steps[$state.current].state -eq 'active') { Set-StepState $state.current 'done' }
        $state.current = $Id; $state.stepStarted = $now; $state.bytesDone = 0; $state.bytesTotal = 0
        $s.started = $now
        $ui.StepTitle.Text = $s.text.Text; $ui.StepDetail.Text = ' '; $ui.StepBytes.Text = ' '
        $s.ring.Stroke = (& $brush $P.track); $s.arc.Visibility = 'Visible'; $s.mark.Visibility = 'Collapsed'
        $s.spin.BeginAnimation([Windows.Media.RotateTransform]::AngleProperty, $s.anim)
        $s.text.Foreground = (& $brush $P.text); $s.text.FontWeight = 'SemiBold'
    } else {
        if ($s.started) { $s.took = ($now - $s.started).TotalSeconds }
        $s.spin.BeginAnimation([Windows.Media.RotateTransform]::AngleProperty, $null)
        $s.arc.Visibility = 'Collapsed'; $s.text.FontWeight = 'Normal'
        $color = @{ done = $P.good; skip = $P.track; warn = $P.warn; fail = $P.bad }[$StepState]
        if (-not $color) { $color = $P.track }
        $s.ring.Fill = (& $brush $color); $s.ring.Stroke = (& $brush $color)
        $s.mark.Data = [Windows.Media.Geometry]::Parse(@{ done = 'M0,3.4 L2.6,6 L7.6,0.6'; warn = 'M0,0 L0,4 M0,6.6 L0,6.8'; fail = 'M0,0 L6,6 M6,0 L0,6'; skip = 'M0,0 L6,0' }[$StepState])
        $s.mark.Visibility = 'Visible'
        $s.text.Foreground = (& $brush $(if ($StepState -eq 'skip') { $P.muted } else { $P.text }))
        $label = if ($Note) { $Note } elseif ($StepState -eq 'skip') { $L.skipped } elseif ($StepState -eq 'warn') { $L.warn } elseif ($s.took -ge 1) { Format-Time $s.took } else { '' }
        $s.note.Text = $label
        if ($state.current -eq $Id) { $state.current = $null }
    }
    $s.state = $StepState
}

function Add-Log([string]$Text) {
    [void]$state.log.AppendLine($Text)
    if ($state.log.Length -gt 60000) { [void]$state.log.Remove(0, 20000) }
    if ($ui.LogBox.Visibility -eq 'Visible') { $ui.LogText.Text = $state.log.ToString(); $ui.LogText.ScrollToEnd() }
}

function Complete([bool]$Ok, [string]$Message) {
    if ($state.finished) { return }
    $state.finished = $true; $state.ok = $Ok
    foreach ($id in @($state.steps.Keys)) {
        $s = $state.steps[$id]
        if ($s.state -eq 'active') { Set-StepState $id $(if ($Ok) { 'done' } else { 'fail' }) }
        elseif ($s.state -eq 'pending' -and $Ok) { Set-StepState $id 'skip' }
    }
    $ui.Shine.Opacity = 0
    # The logo pulse is only hidden: removing its animation from PowerShell froze the window timer.
    $ui.Pulse.Visibility = 'Collapsed'
    $ui.Result.Visibility = 'Visible'
    if ($Ok) {
        $ui.Result.Background = (& $brush (Join-Color $P.surface $P.good 0.14))
        $ui.ResultTitle.Text = if ($Mode -eq 'install') { $L.doneInstall } else { $L.doneUpdate }
        $ui.ResultText.Text = $Message
        $ui.StepTitle.Text = $ui.ResultTitle.Text; $ui.StepDetail.Text = ' '
        $ui.Percent.Text = '100%'; $ui.Eta.Text = ' '; $state.shownProgress = 1.0
        $ui.LaunchButton.Visibility = 'Visible'; $ui.FinishButton.Visibility = 'Visible'
        $state.countdown = 60
    } else {
        $ui.Result.Background = (& $brush (Join-Color $P.surface $P.bad 0.16))
        $ui.ResultTitle.Text = $L.failed; $ui.ResultText.Text = $Message
        $ui.StepTitle.Text = $L.failed; $ui.Eta.Text = ' '
        $ui.Bar.Background = (& $brush $P.bad)
        $ui.LogButton.Visibility = 'Visible'; $ui.FinishButton.Visibility = 'Visible'
        if ($ui.LogBox.Visibility -ne 'Visible') { Show-Details $true }
    }
    $ui.CloseButton.Visibility = 'Visible'
    $window.Activate() | Out-Null
}

function Show-Details([bool]$Open) {
    if ($Open) {
        $ui.LogBox.Visibility = 'Visible'; $ui.DetailsText.Text = $L.hide; $ui.ChevronTurn.Angle = 0
        $ui.LogText.Text = $state.log.ToString(); $ui.LogText.ScrollToEnd()
    } else {
        $ui.LogBox.Visibility = 'Collapsed'; $ui.DetailsText.Text = $L.details; $ui.ChevronTurn.Angle = -90
    }
}

function Get-EventText($E, [string]$Field = 'text') {
    $names = $E.PSObject.Properties.Name
    if ($names -contains $language -and $E.$language) { return [string]$E.$language }
    if ($names -contains $Field -and $E.$Field) { return [string]$E.$Field }
    return ''
}

function Read-Events {
    if (-not (Test-Path -LiteralPath $Events)) { return }
    $stream = $null
    try {
        $stream = [IO.File]::Open($Events, 'Open', 'Read', 'ReadWrite')
        if ($stream.Length -lt $state.position) { $state.position = 0 }
        [void]$stream.Seek($state.position, 'Begin')
        $reader = New-Object IO.StreamReader($stream, [Text.Encoding]::UTF8)
        $chunk = $reader.ReadToEnd()
        $last = $chunk.LastIndexOf("`n")
        if ($last -lt 0) { return }
        $state.position += [Text.Encoding]::UTF8.GetByteCount($chunk.Substring(0, $last + 1))
        foreach ($line in $chunk.Substring(0, $last).Split("`n")) {
            $line = $line.Trim(); if (-not $line) { continue }
            try { $e = $line | ConvertFrom-Json } catch { continue }
            switch ([string]$e.t) {
                'plan' {
                    if ($e.PSObject.Properties.Name -contains 'version' -and $e.version) { $ui.Subtitle.Text = ($L.version -f $e.version) }
                    foreach ($step in $e.steps) {
                        if (-not $state.steps.Contains([string]$step.id)) { $state.steps[[string]$step.id] = New-StepRow ([string]$step.id) }
                        $state.steps[[string]$step.id].weight = [double]$step.w
                    }
                }
                'step' { $note = ''; if ($e.PSObject.Properties.Name -contains 'note' -and $e.note) { $note = [string]$e.note }; Set-StepState ([string]$e.id) ([string]$e.state) $note }
                'detail' { $ui.StepDetail.Text = (Get-EventText $e) }
                'log' { Add-Log (Get-EventText $e) }
                'bytes' {
                    $state.bytesDone = [double]$e.done; $state.bytesTotal = [double]$e.total
                    $ui.StepBytes.Text = if ($state.bytesTotal -gt 0) { '{0} / {1}' -f (Format-Bytes $state.bytesDone), (Format-Bytes $state.bytesTotal) } else { Format-Bytes $state.bytesDone }
                }
                'done' { Complete ([bool]$e.ok) (Get-EventText $e 'message') }
            }
        }
    } catch { } finally { if ($stream) { $stream.Dispose() } }
}

function Update-Progress {
    $total = 0.0; $done = 0.0; $ratios = @()
    foreach ($s in $state.steps.Values) {
        $total += $s.weight
        if ($s.state -in @('done', 'warn', 'skip', 'fail')) {
            $done += $s.weight
            if ($s.state -ne 'skip' -and $s.took -gt 0.5) { $ratios += [Math]::Min(3.0, [Math]::Max(0.3, $s.took / $s.weight)) }
        }
    }
    if ($total -le 0) { return }
    $pace = if ($ratios.Count) { ($ratios | Measure-Object -Average).Average } else { 1.0 }
    $currentLeft = 0.0
    if ($state.current) {
        $s = $state.steps[$state.current]
        $spent = ([DateTime]::Now - $state.stepStarted).TotalSeconds
        if ($state.bytesTotal -gt 0) {
            $fraction = [Math]::Min(0.99, $state.bytesDone / $state.bytesTotal)
            $currentLeft = if ($state.speed -gt 20000) { ($state.bytesTotal - $state.bytesDone) / $state.speed } else { $s.weight * $pace * (1 - $fraction) }
        } else {
            $expected = $s.weight * $pace
            $fraction = [Math]::Min(0.92, $spent / [Math]::Max(1.0, $expected) * 0.92)
            $currentLeft = [Math]::Max(2.0, $expected - $spent)
        }
        $done += $s.weight * $fraction
    }
    $target = [Math]::Min(0.99, $done / $total)
    if ($target -gt $state.shownProgress) { $state.shownProgress += ($target - $state.shownProgress) * 0.25 }
    $ui.Percent.Text = ('{0}%' -f [int]($state.shownProgress * 100))
    $left = $currentLeft
    foreach ($s in $state.steps.Values) { if ($s.state -eq 'pending') { $left += $s.weight * $pace } }
    $ui.Eta.Text = Format-Left $left
}

function Update-Speed {
    $now = [DateTime]::Now
    $rx = Get-ReceivedBytes
    if ($state.lastRx -ge 0) {
        $seconds = ($now - $state.lastRxAt).TotalSeconds
        if ($seconds -gt 0.2) {
            $delta = [Math]::Max(0.0, $rx - $state.lastRx)
            $state.downloaded += $delta
            $instant = $delta / $seconds
            $state.speed = if ($state.speed -le 0) { $instant } else { $state.speed * 0.55 + $instant * 0.45 }
            [void]$state.samples.Add($state.speed); while ($state.samples.Count -gt 40) { $state.samples.RemoveAt(0) }
        }
    }
    $state.lastRx = $rx; $state.lastRxAt = $now
    $ui.Speed.Text = if ($state.speed -ge 1MB) { '{0:0.0} MB/s' -f ($state.speed / 1MB) } else { '{0:0} KB/s' -f ($state.speed / 1KB) }
    $ui.SpeedBits.Text = '{0:0.#} Mbit/s' -f ($state.speed * 8 / 1000000)
    $ui.Downloaded.Text = Format-Bytes $state.downloaded
    # sparkline
    $w = 96.0; $h = 40.0; $n = $state.samples.Count
    if ($n -ge 2) {
        $max = [Math]::Max(256KB, ($state.samples | Measure-Object -Maximum).Maximum)
        $points = New-Object Windows.Media.PointCollection
        for ($i = 0; $i -lt $n; $i++) {
            $x = $w * $i / 39.0 + ($w - $w * ($n - 1) / 39.0)
            $points.Add((New-Object Windows.Point $x, ($h - 3 - ($h - 6) * $state.samples[$i] / $max)))
        }
        $ui.GraphLine.Points = $points
        $fill = New-Object Windows.Media.PointCollection
        $fill.Add((New-Object Windows.Point $points[0].X, $h)); foreach ($p in $points) { $fill.Add($p) }; $fill.Add((New-Object Windows.Point $w, $h))
        $ui.GraphFill.Points = $fill
    }
}

# ---------------------------------------------------------------- behaviour
$ui.Header.Add_MouseLeftButtonDown({ try { $window.DragMove() } catch { } })
$ui.MinButton.Add_Click({ $window.WindowState = 'Minimized' })
$ui.CloseButton.Add_Click({ $window.Close() })
$ui.FinishButton.Add_Click({ $window.Close() })
$ui.DetailsButton.Add_Click({ Show-Details ($ui.LogBox.Visibility -ne 'Visible') })
$ui.LogButton.Add_Click({
        $log = if ($Mode -eq 'install') { Join-Path $Root 'logs\install_windows.log' } else { $Events }
        try { Start-Process notepad.exe -ArgumentList "`"$log`"" } catch { }
    })
$ui.LaunchButton.Add_Click({
        try { Start-Process -FilePath (Join-Path $Root 'run_windows.bat') -WorkingDirectory $Root -WindowStyle Hidden } catch { }
        $window.Close()
    })
# While working the window cannot be closed (only minimised): the work would go on unseen.
$window.Add_Closing({ param($sender, $e) if (-not $state.finished) { $e.Cancel = $true; $window.WindowState = 'Minimized' } })

# Pulse of the logo and the shine on the bar while working.
$pulse = New-Object Windows.Media.Animation.DoubleAnimation 1.0, 1.32, ([TimeSpan]::FromSeconds(1.6))
$pulse.RepeatBehavior = [Windows.Media.Animation.RepeatBehavior]::Forever
$fade = New-Object Windows.Media.Animation.DoubleAnimation 0.55, 0.0, ([TimeSpan]::FromSeconds(1.6))
$fade.RepeatBehavior = [Windows.Media.Animation.RepeatBehavior]::Forever
$ui.PulseScale.BeginAnimation([Windows.Media.ScaleTransform]::ScaleXProperty, $pulse)
$ui.PulseScale.BeginAnimation([Windows.Media.ScaleTransform]::ScaleYProperty, $pulse)
$ui.Pulse.BeginAnimation([Windows.UIElement]::OpacityProperty, $fade)
$window.Opacity = 0
$window.Add_Loaded({
        $appear = New-Object Windows.Media.Animation.DoubleAnimation 0.0, 1.0, ([TimeSpan]::FromMilliseconds(260))
        $window.BeginAnimation([Windows.UIElement]::OpacityProperty, $appear)
        if ($Ready) { try { Set-Content -LiteralPath $Ready -Value 'ready' -Encoding ASCII } catch { } }
    })

# Developer check only: LUXAI_UI_SNAPSHOT="C:\dir;3,9" saves the window as PNG after 3 and 9 seconds.
if ($env:LUXAI_UI_SNAPSHOT) {
    $parts = $env:LUXAI_UI_SNAPSHOT.Split(';')
    $state.snapshots = New-Object System.Collections.ArrayList
    foreach ($at in $parts[1].Split(',')) { [void]$state.snapshots.Add([double]$at) }
    $state.snapshotDir = $parts[0]
}
function Save-Snapshot([string]$Path) {
    $content = $window.Content
    $w = [int]$content.ActualWidth + 36; $h = [int]$content.ActualHeight + 36
    $visual = New-Object Windows.Media.DrawingVisual
    $dc = $visual.RenderOpen()
    $dc.DrawRectangle((& $brush '#202020'), $null, (New-Object Windows.Rect 0, 0, $w, $h))
    $vb = New-Object Windows.Media.VisualBrush $content
    $dc.DrawRectangle($vb, $null, (New-Object Windows.Rect 18, 18, $content.ActualWidth, $content.ActualHeight))
    $dc.Close()
    $bmp = New-Object Windows.Media.Imaging.RenderTargetBitmap $w, $h, 96, 96, ([Windows.Media.PixelFormats]::Pbgra32)
    $bmp.Render($visual)
    $encoder = New-Object Windows.Media.Imaging.PngBitmapEncoder
    $encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bmp))
    $file = [IO.File]::Create($Path); try { $encoder.Save($file) } finally { $file.Dispose() }
}

$fast = New-Object Windows.Threading.DispatcherTimer
$fast.Interval = [TimeSpan]::FromMilliseconds(120)
$tick = 0
$fast.Add_Tick({
    try {
        Read-Events
        if ($state.Contains('snapshots') -and $state.snapshots.Count) {
            $age = ([DateTime]::Now - $state.started).TotalSeconds
            if ($age -ge $state.snapshots[0]) {
                try { Save-Snapshot (Join-Path $state.snapshotDir ('ui_{0:00}.png' -f [int]$state.snapshots[0])) } catch { }
                $state.snapshots.RemoveAt(0)
            }
        }
        if (-not $state.finished) {
            Update-Progress
            $script:tick++
            # bar width follows the shown progress
            $full = $ui.Bar.Parent.ActualWidth
            $ui.Bar.Width = [Math]::Max(8, $full * $state.shownProgress)
            $ui.Shine.Opacity = 1; $ui.ShineMove.X = (($script:tick * 6) % [Math]::Max(80, $ui.Bar.Width + 70)) - 70
            if ($ui.ShineMove.X + 70 -gt $ui.Bar.Width) { $ui.Shine.Opacity = 0 }
            if ($script:tick % 8 -eq 0) {
                Update-Speed
                $ui.Elapsed.Text = Format-Time (([DateTime]::Now - $state.started).TotalSeconds)
                if ($ProducerPid -gt 0 -and -not (Get-Process -Id $ProducerPid -ErrorAction SilentlyContinue)) {
                    Read-Events
                    if (-not $state.finished) { Complete $false $L.stopped }
                }
            }
        } else {
            $ui.Bar.Width = $ui.Bar.Parent.ActualWidth * $(if ($state.ok) { 1.0 } else { [Math]::Max(0.04, $state.shownProgress) })
            $script:tick++
            if ($state.ok -and $state.countdown -ge 0 -and $script:tick % 8 -eq 0) {
                $ui.Countdown.Text = ($L.closesIn -f $state.countdown)
                # Counts down every second; it only waits while the details are open (being read).
                if ($ui.LogBox.Visibility -eq 'Visible') { $ui.Countdown.Text = '' } else { $state.countdown-- }
                if ($state.countdown -lt 0) { $window.Close() }
            }
        }
    } catch {
        # One failed tick must not stop the window; developers see why.
        if ($env:LUXAI_UI_SNAPSHOT) { try { Add-Content -LiteralPath (Join-Path $env:TEMP 'luxai_ui_errors.txt') -Value ($_ | Out-String) } catch { } }
    }
    })
$fast.Start()
[void]$window.ShowDialog()
