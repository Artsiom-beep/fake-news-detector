import 'dart:async';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';

void main() {
  runApp(const FakeNewsDetectorApp());
}

String normalizeApiBaseUrl(String value) {
  final trimmed = value.trim();
  if (trimmed.isEmpty) {
    return defaultApiBaseUrl;
  }
  return trimmed.endsWith('/')
      ? trimmed.substring(0, trimmed.length - 1)
      : trimmed;
}

bool isLocalOrPrivateApiUrl(String value) {
  final uri = Uri.tryParse(value.trim());
  final host = uri?.host.toLowerCase() ?? '';
  if (host.isEmpty) {
    return false;
  }
  if (host == 'localhost' || host == '0.0.0.0' || host == '::1') {
    return true;
  }
  if (host == '10.0.2.2' || host.startsWith('127.') || host.startsWith('10.')) {
    return true;
  }
  if (host.startsWith('192.168.')) {
    return true;
  }
  final parts = host.split('.');
  if (parts.length == 4 && parts[0] == '172') {
    final second = int.tryParse(parts[1]);
    return second != null && second >= 16 && second <= 31;
  }
  return false;
}

bool isPublicInternetApiUrl(String value) {
  final uri = Uri.tryParse(value.trim());
  if (uri == null || uri.scheme != 'https' || uri.host.isEmpty) {
    return false;
  }
  return !isLocalOrPrivateApiUrl(value);
}

String? validateApiBaseUrl(String value) {
  final normalized = normalizeApiBaseUrl(value);
  final uri = Uri.tryParse(normalized);
  if (uri == null || uri.host.isEmpty) {
    return 'Enter a full API URL, for example https://your-app.onrender.com';
  }
  if (uri.scheme != 'http' && uri.scheme != 'https') {
    return 'API URL must start with http:// or https://';
  }
  return null;
}

bool shouldPreferBuildDefaultApiUrl({
  required String savedUrl,
  required String buildDefaultUrl,
}) {
  return isPublicInternetApiUrl(buildDefaultUrl) &&
      isLocalOrPrivateApiUrl(savedUrl);
}

class FakeNewsDetectorApp extends StatefulWidget {
  const FakeNewsDetectorApp({
    super.key,
    this.gateway,
    this.enableBackendStatus = true,
  });

  final FactCheckGateway? gateway;
  final bool enableBackendStatus;

  @override
  State<FakeNewsDetectorApp> createState() => _FakeNewsDetectorAppState();
}

class _FakeNewsDetectorAppState extends State<FakeNewsDetectorApp> {
  static const _apiBaseUrlKey = 'api_base_url';

  late String _apiBaseUrl;
  late FactCheckGateway _gateway;

  bool get _usesInjectedGateway => widget.gateway != null;

  @override
  void initState() {
    super.initState();
    _apiBaseUrl = defaultApiBaseUrl;
    _gateway = widget.gateway ?? FactCheckApiClient(baseUrl: _apiBaseUrl);
    if (!_usesInjectedGateway) {
      _loadApiBaseUrl();
    }
  }

  @override
  void didUpdateWidget(covariant FakeNewsDetectorApp oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.gateway != null && widget.gateway != oldWidget.gateway) {
      _gateway = widget.gateway!;
    }
  }

  Future<void> _loadApiBaseUrl() async {
    final prefs = await SharedPreferences.getInstance();
    final savedUrl = prefs.getString(_apiBaseUrlKey);
    if (!mounted || savedUrl == null || savedUrl.trim().isEmpty) {
      return;
    }
    final normalizedUrl = normalizeApiBaseUrl(savedUrl);
    if (shouldPreferBuildDefaultApiUrl(
      savedUrl: normalizedUrl,
      buildDefaultUrl: defaultApiBaseUrl,
    )) {
      await prefs.remove(_apiBaseUrlKey);
      return;
    }
    setState(() {
      _apiBaseUrl = normalizedUrl;
      _gateway = FactCheckApiClient(baseUrl: normalizedUrl);
    });
  }

  Future<void> _saveApiBaseUrl(String value) async {
    final normalizedUrl = normalizeApiBaseUrl(value);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_apiBaseUrlKey, normalizedUrl);
    if (!mounted) {
      return;
    }
    setState(() {
      _apiBaseUrl = normalizedUrl;
      _gateway = FactCheckApiClient(baseUrl: normalizedUrl);
    });
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Verity Lens',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.theme,
      home: VerificationHome(
        gateway: _gateway,
        apiBaseUrl: _usesInjectedGateway ? null : _apiBaseUrl,
        onApiBaseUrlChanged: _usesInjectedGateway ? null : _saveApiBaseUrl,
        enableBackendStatus: widget.enableBackendStatus,
      ),
    );
  }
}

class VerificationHome extends StatefulWidget {
  const VerificationHome({
    super.key,
    required this.gateway,
    this.apiBaseUrl,
    this.onApiBaseUrlChanged,
    this.enableBackendStatus = true,
  });

  final FactCheckGateway gateway;
  final String? apiBaseUrl;
  final Future<void> Function(String value)? onApiBaseUrlChanged;
  final bool enableBackendStatus;

  @override
  State<VerificationHome> createState() => _VerificationHomeState();
}

class _VerificationHomeState extends State<VerificationHome> {
  final _newsUrlController = TextEditingController();
  final _newsTextController = TextEditingController();
  final _factController = TextEditingController();
  final _screenshotQuestionController = TextEditingController();
  final _imageContextController = TextEditingController();

  int _selectedIndex = 0;
  bool _isLoading = false;
  String? _error;
  FactCheckResult? _result;
  PickedImage? _screenshot;
  PickedImage? _image;
  BackendReachability _backendReachability = BackendReachability.unchecked;
  String _backendMessage = '';

  @override
  void initState() {
    super.initState();
    if (widget.enableBackendStatus) {
      unawaited(_refreshBackendStatus());
    }
  }

  @override
  void didUpdateWidget(covariant VerificationHome oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.enableBackendStatus &&
        (widget.gateway != oldWidget.gateway ||
            widget.apiBaseUrl != oldWidget.apiBaseUrl)) {
      unawaited(_refreshBackendStatus());
    }
  }

  @override
  void dispose() {
    _newsUrlController.dispose();
    _newsTextController.dispose();
    _factController.dispose();
    _screenshotQuestionController.dispose();
    _imageContextController.dispose();
    super.dispose();
  }

  Future<void> _refreshBackendStatus() async {
    setState(() {
      _backendReachability = BackendReachability.checking;
      _backendMessage = 'Checking API connection...';
    });
    final status = await widget.gateway.checkHealth();
    if (!mounted) {
      return;
    }
    setState(() {
      _backendReachability = status.isReachable
          ? BackendReachability.online
          : BackendReachability.offline;
      _backendMessage = status.isReachable
          ? 'Connected to ${status.service.isEmpty ? 'factcheck API' : status.service}'
          : status.message;
    });
  }

  Future<void> _run(Future<FactCheckResult> Function() action) async {
    setState(() {
      _isLoading = true;
      _error = null;
      _result = null;
    });
    try {
      final result = await action();
      if (!mounted) {
        return;
      }
      setState(() => _result = result);
    } on FactCheckApiException catch (error) {
      if (!mounted) {
        return;
      }
      setState(() => _error = error.message);
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() => _error =
          'The check could not be completed. Verify the API URL and internet connection.');
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  Future<void> _pickImage(ImageSlot slot) async {
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.image,
      withData: true,
    );
    final file = picked?.files.single;
    if (file == null || file.bytes == null) {
      return;
    }
    setState(() {
      final image = PickedImage(name: file.name, bytes: file.bytes!);
      if (slot == ImageSlot.screenshot) {
        _screenshot = image;
      } else {
        _image = image;
      }
    });
  }

  Future<void> _checkNews() {
    return _run(
      () => widget.gateway.checkText(
        url: _newsUrlController.text,
        text: _newsTextController.text,
      ),
    );
  }

  Future<void> _checkFact() {
    return _run(() => widget.gateway.checkText(text: _factController.text));
  }

  Future<void> _checkScreenshot() {
    final screenshot = _screenshot;
    if (screenshot == null) {
      setState(() => _error = 'Choose a screenshot first.');
      return Future<void>.value();
    }
    return _run(
      () => widget.gateway.checkImage(
        bytes: screenshot.bytes,
        filename: screenshot.name,
        analysisType: ImageAnalysisType.screenshot,
        question: _screenshotQuestionController.text,
      ),
    );
  }

  Future<void> _checkAiImage() {
    final image = _image;
    if (image == null) {
      setState(() => _error = 'Choose an image first.');
      return Future<void>.value();
    }
    return _run(
      () => widget.gateway.checkImage(
        bytes: image.bytes,
        filename: image.name,
        analysisType: ImageAnalysisType.aiImage,
        question: _imageContextController.text,
      ),
    );
  }

  Future<void> _showApiSettings() async {
    final value = await showDialog<String>(
      context: context,
      builder: (context) => _ApiSettingsDialog(
          initialUrl: widget.apiBaseUrl ?? defaultApiBaseUrl),
    );

    final save = widget.onApiBaseUrlChanged;
    if (value == null || save == null) {
      return;
    }
    if (!mounted) {
      return;
    }
    final validationError = validateApiBaseUrl(value);
    if (validationError != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(validationError)),
      );
      return;
    }
    await save(value);
    if (!mounted) {
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('API URL saved')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final modes = _modes();
    final selectedMode = modes[_selectedIndex];
    return Scaffold(
      appBar: AppBar(
        title: const Text('Verity Lens'),
        centerTitle: false,
        actions: [
          if (widget.onApiBaseUrlChanged != null)
            IconButton(
              tooltip: 'API settings',
              icon: const Icon(Icons.settings),
              onPressed: _showApiSettings,
            ),
        ],
      ),
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final content = _BodyContent(
              mode: selectedMode,
              result: _result,
              error: _error,
              isLoading: _isLoading,
              apiBaseUrl: widget.apiBaseUrl,
              backendReachability: _backendReachability,
              backendMessage: _backendMessage,
              showBackendStatus: widget.enableBackendStatus,
              onRefreshBackendStatus: _refreshBackendStatus,
            );
            if (constraints.maxWidth >= 760) {
              return Row(
                children: [
                  NavigationRail(
                    selectedIndex: _selectedIndex,
                    onDestinationSelected: (index) =>
                        setState(() => _selectedIndex = index),
                    labelType: NavigationRailLabelType.all,
                    destinations: [
                      for (final mode in modes)
                        NavigationRailDestination(
                          icon: Icon(mode.icon),
                          selectedIcon: Icon(mode.selectedIcon),
                          label: Text(mode.label),
                        ),
                    ],
                  ),
                  const VerticalDivider(width: 1),
                  Expanded(child: content),
                ],
              );
            }
            return content;
          },
        ),
      ),
      bottomNavigationBar: LayoutBuilder(
        builder: (context, constraints) {
          if (constraints.maxWidth >= 760) {
            return const SizedBox.shrink();
          }
          return NavigationBar(
            selectedIndex: _selectedIndex,
            onDestinationSelected: (index) =>
                setState(() => _selectedIndex = index),
            destinations: [
              for (final mode in modes)
                NavigationDestination(
                  icon: Icon(mode.icon),
                  selectedIcon: Icon(mode.selectedIcon),
                  label: mode.label,
                ),
            ],
          );
        },
      ),
    );
  }

  List<VerificationMode> _modes() {
    return [
      VerificationMode(
        label: 'News',
        icon: Icons.article_outlined,
        selectedIcon: Icons.article,
        color: const Color(0xffa95f3d),
        child: NewsPanel(
          urlController: _newsUrlController,
          textController: _newsTextController,
          onSubmit: _checkNews,
          isLoading: _isLoading,
        ),
      ),
      VerificationMode(
        label: 'Facts',
        icon: Icons.fact_check_outlined,
        selectedIcon: Icons.fact_check,
        color: const Color(0xff8b6a16),
        child: FactsPanel(
          controller: _factController,
          onSubmit: _checkFact,
          isLoading: _isLoading,
        ),
      ),
      VerificationMode(
        label: 'Screenshots',
        icon: Icons.screenshot_monitor_outlined,
        selectedIcon: Icons.screenshot_monitor,
        color: const Color(0xff2e6f64),
        child: ImagePanel(
          title: 'Screenshots',
          contextLabel: 'Question',
          contextController: _screenshotQuestionController,
          selectedImage: _screenshot,
          actionLabel: 'Check screenshot',
          onPick: () => _pickImage(ImageSlot.screenshot),
          onSubmit: _checkScreenshot,
          isLoading: _isLoading,
        ),
      ),
      VerificationMode(
        label: 'Images',
        icon: Icons.image_search_outlined,
        selectedIcon: Icons.image_search,
        color: const Color(0xff8d4d6f),
        child: ImagePanel(
          title: 'Photos / images',
          contextLabel: 'Context',
          contextController: _imageContextController,
          selectedImage: _image,
          actionLabel: 'Detect AI image',
          onPick: () => _pickImage(ImageSlot.image),
          onSubmit: _checkAiImage,
          isLoading: _isLoading,
        ),
      ),
    ];
  }
}

class _ApiSettingsDialog extends StatefulWidget {
  const _ApiSettingsDialog({required this.initialUrl});

  final String initialUrl;

  @override
  State<_ApiSettingsDialog> createState() => _ApiSettingsDialogState();
}

class _ApiSettingsDialogState extends State<_ApiSettingsDialog> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initialUrl);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('API settings'),
      content: TextField(
        controller: _controller,
        keyboardType: TextInputType.url,
        textInputAction: TextInputAction.done,
        decoration: const InputDecoration(
          labelText: 'API URL',
          hintText: 'https://your-app.onrender.com',
        ),
        onSubmitted: (value) => Navigator.of(context).pop(value),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(_controller.text),
          child: const Text('Save'),
        ),
      ],
    );
  }
}

class _BodyContent extends StatelessWidget {
  const _BodyContent({
    required this.mode,
    required this.result,
    required this.error,
    required this.isLoading,
    required this.apiBaseUrl,
    required this.backendReachability,
    required this.backendMessage,
    required this.showBackendStatus,
    required this.onRefreshBackendStatus,
  });

  final VerificationMode mode;
  final FactCheckResult? result;
  final String? error;
  final bool isLoading;
  final String? apiBaseUrl;
  final BackendReachability backendReachability;
  final String backendMessage;
  final bool showBackendStatus;
  final Future<void> Function() onRefreshBackendStatus;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 28),
      children: [
        if (showBackendStatus) ...[
          BackendStatusBanner(
            apiBaseUrl: apiBaseUrl,
            reachability: backendReachability,
            message: backendMessage,
            onRefresh: onRefreshBackendStatus,
          ),
          const SizedBox(height: 12),
        ],
        _ModeHeader(mode: mode),
        const SizedBox(height: 12),
        mode.child,
        if (isLoading) ...[
          const SizedBox(height: 18),
          const LinearProgressIndicator(),
        ],
        if (error != null) ...[
          const SizedBox(height: 18),
          ErrorBanner(message: error!),
        ],
        if (result != null) ...[
          const SizedBox(height: 18),
          ResultCard(result: result!),
        ],
      ],
    );
  }
}

enum BackendReachability { unchecked, checking, online, offline }

class BackendStatusBanner extends StatelessWidget {
  const BackendStatusBanner({
    super.key,
    required this.apiBaseUrl,
    required this.reachability,
    required this.message,
    required this.onRefresh,
  });

  final String? apiBaseUrl;
  final BackendReachability reachability;
  final String message;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    final online = reachability == BackendReachability.online;
    final checking = reachability == BackendReachability.checking;
    final color = switch (reachability) {
      BackendReachability.online => const Color(0xff146c48),
      BackendReachability.offline => const Color(0xff963333),
      BackendReachability.checking => const Color(0xff9a6400),
      BackendReachability.unchecked => const Color(0xff475467),
    };
    final title = switch (reachability) {
      BackendReachability.online => 'API connected',
      BackendReachability.offline => 'API not reachable',
      BackendReachability.checking => 'Checking API',
      BackendReachability.unchecked => 'API not checked',
    };
    final details = [
      if (apiBaseUrl != null && apiBaseUrl!.isNotEmpty) apiBaseUrl!,
      if (message.isNotEmpty) message,
    ].join(' | ');

    return Container(
      decoration: BoxDecoration(
        color: color.withValues(alpha: .10),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: .22)),
      ),
      padding: const EdgeInsets.fromLTRB(12, 10, 8, 10),
      child: Row(
        children: [
          if (checking)
            SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: color,
              ),
            )
          else
            Icon(
              online ? Icons.cloud_done : Icons.cloud_off,
              color: color,
            ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: TextStyle(
                    color: color,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                if (details.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(
                    details,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 12),
                  ),
                ],
              ],
            ),
          ),
          IconButton(
            tooltip: 'Check API connection',
            onPressed: checking ? null : () => unawaited(onRefresh()),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
    );
  }
}

class _ModeHeader extends StatelessWidget {
  const _ModeHeader({required this.mode});

  final VerificationMode mode;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: mode.color.withValues(alpha: .12),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: mode.color.withValues(alpha: .24)),
      ),
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Icon(mode.selectedIcon, color: mode.color),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              mode.label,
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    color: const Color(0xff18202f),
                    fontWeight: FontWeight.w800,
                  ),
            ),
          ),
        ],
      ),
    );
  }
}

class NewsPanel extends StatelessWidget {
  const NewsPanel({
    super.key,
    required this.urlController,
    required this.textController,
    required this.onSubmit,
    required this.isLoading,
  });

  final TextEditingController urlController;
  final TextEditingController textController;
  final VoidCallback onSubmit;
  final bool isLoading;

  @override
  Widget build(BuildContext context) {
    return FormSurface(
      children: [
        AppTextField(
          controller: urlController,
          label: 'News URL',
          keyboardType: TextInputType.url,
          textInputAction: TextInputAction.next,
        ),
        AppTextField(
          controller: textController,
          label: 'Article note',
          minLines: 4,
          maxLines: 7,
        ),
        PrimaryActionButton(
          label: 'Check news',
          icon: Icons.search,
          onPressed: isLoading ? null : onSubmit,
        ),
      ],
    );
  }
}

class FactsPanel extends StatelessWidget {
  const FactsPanel({
    super.key,
    required this.controller,
    required this.onSubmit,
    required this.isLoading,
  });

  final TextEditingController controller;
  final VoidCallback onSubmit;
  final bool isLoading;

  @override
  Widget build(BuildContext context) {
    return FormSurface(
      children: [
        AppTextField(
          controller: controller,
          label: 'Claim',
          minLines: 5,
          maxLines: 8,
        ),
        PrimaryActionButton(
          label: 'Check fact',
          icon: Icons.fact_check,
          onPressed: isLoading ? null : onSubmit,
        ),
      ],
    );
  }
}

class ImagePanel extends StatelessWidget {
  const ImagePanel({
    super.key,
    required this.title,
    required this.contextLabel,
    required this.contextController,
    required this.selectedImage,
    required this.actionLabel,
    required this.onPick,
    required this.onSubmit,
    required this.isLoading,
  });

  final String title;
  final String contextLabel;
  final TextEditingController contextController;
  final PickedImage? selectedImage;
  final String actionLabel;
  final VoidCallback onPick;
  final VoidCallback onSubmit;
  final bool isLoading;

  @override
  Widget build(BuildContext context) {
    return FormSurface(
      children: [
        OutlinedButton.icon(
          onPressed: isLoading ? null : onPick,
          icon: const Icon(Icons.upload_file),
          label: Text(selectedImage?.name ?? 'Choose image'),
        ),
        if (selectedImage != null)
          ImagePreview(
            title: title,
            image: selectedImage!,
          ),
        AppTextField(
          controller: contextController,
          label: contextLabel,
          minLines: 3,
          maxLines: 5,
        ),
        PrimaryActionButton(
          label: actionLabel,
          icon: Icons.search,
          onPressed: isLoading ? null : onSubmit,
        ),
      ],
    );
  }
}

class FormSurface extends StatelessWidget {
  const FormSurface({super.key, required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (final child in children) ...[
              child,
              if (child != children.last) const SizedBox(height: 12),
            ],
          ],
        ),
      ),
    );
  }
}

class AppTextField extends StatelessWidget {
  const AppTextField({
    super.key,
    required this.controller,
    required this.label,
    this.keyboardType,
    this.textInputAction,
    this.minLines = 1,
    this.maxLines = 1,
  });

  final TextEditingController controller;
  final String label;
  final TextInputType? keyboardType;
  final TextInputAction? textInputAction;
  final int minLines;
  final int maxLines;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      keyboardType: keyboardType,
      textInputAction: textInputAction,
      minLines: minLines,
      maxLines: maxLines,
      decoration: InputDecoration(labelText: label),
    );
  }
}

class PrimaryActionButton extends StatelessWidget {
  const PrimaryActionButton({
    super.key,
    required this.label,
    required this.icon,
    required this.onPressed,
  });

  final String label;
  final IconData icon;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return FilledButton.icon(
      onPressed: onPressed,
      icon: Icon(icon),
      label: Text(label),
    );
  }
}

class ImagePreview extends StatelessWidget {
  const ImagePreview({super.key, required this.title, required this.image});

  final String title;
  final PickedImage image;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: AspectRatio(
        aspectRatio: 16 / 9,
        child: Image.memory(
          image.bytes,
          fit: BoxFit.cover,
          semanticLabel: title,
        ),
      ),
    );
  }
}

class ErrorBanner extends StatelessWidget {
  const ErrorBanner({super.key, required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xfff6dddd),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xffd89a9a)),
      ),
      child: Text(
        message,
        style: const TextStyle(
            color: Color(0xff7a2323), fontWeight: FontWeight.w700),
      ),
    );
  }
}

class ResultCard extends StatelessWidget {
  const ResultCard({super.key, required this.result});

  final FactCheckResult result;

  @override
  Widget build(BuildContext context) {
    final status = result.statusView;
    final toneColor = switch (status.tone) {
      StatusTone.good => const Color(0xff146c48),
      StatusTone.warn => const Color(0xff9a6400),
      StatusTone.bad => const Color(0xff963333),
      StatusTone.neutral => const Color(0xff475467),
    };

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Chip(
              label: Text(status.label),
              side: BorderSide(color: toneColor.withValues(alpha: .22)),
              backgroundColor: toneColor.withValues(alpha: .12),
              labelStyle:
                  TextStyle(color: toneColor, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 10),
            if (result.claim.isNotEmpty)
              Text(
                result.claim,
                style: Theme.of(context)
                    .textTheme
                    .titleLarge
                    ?.copyWith(fontWeight: FontWeight.w800),
              ),
            if (result.summary.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(result.summary),
            ],
            const SizedBox(height: 14),
            Text(
                '${status.scoreLabel}: ${(status.score * 100).clamp(0, 100).toDouble().toStringAsFixed(0)}%'),
            const SizedBox(height: 6),
            LinearProgressIndicator(
              value: status.score.clamp(0, 1).toDouble(),
              color: toneColor,
              backgroundColor: const Color(0xffe7d9c5),
            ),
            if (result.credibility.isNotEmpty)
              CredibilitySection(credibility: result.credibility),
            if (result.imageAnalysis.isNotEmpty)
              ImageAnalysisSection(analysis: result.imageAnalysis),
            if (result.evidence.isNotEmpty)
              EvidenceSection(evidence: result.evidence),
          ],
        ),
      ),
    );
  }
}

class CredibilitySection extends StatelessWidget {
  const CredibilitySection({super.key, required this.credibility});

  final Map<String, dynamic> credibility;

  @override
  Widget build(BuildContext context) {
    final riskFlags =
        _stringList(credibility['risk_flags']).take(5).toList(growable: false);
    final matchedSources =
        (credibility['matched_sources'] as List?) ?? const [];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 16),
        Text('News credibility',
            style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 10),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            _MetricChip(
              label: 'Source',
              value: _percent(credibility['source_score']),
            ),
            _MetricChip(
              label: 'Article',
              value: _percent(credibility['article_quality_score']),
            ),
            _MetricChip(
              label: 'Corroboration',
              value: _percent(credibility['corroboration_score']),
            ),
            _MetricChip(
              label: 'Risk',
              value: _percent(credibility['risk_score']),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Text('${matchedSources.length} independent matched sources'),
        if (riskFlags.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text('Risk flags: ${riskFlags.join(', ')}'),
        ],
      ],
    );
  }
}

class ImageAnalysisSection extends StatelessWidget {
  const ImageAnalysisSection({super.key, required this.analysis});

  final Map<String, dynamic> analysis;

  @override
  Widget build(BuildContext context) {
    final ocrText = (analysis['ocr_text'] as String?) ?? '';
    final warnings = _stringList(analysis['warnings']);
    final reasons = (analysis['reasons'] as List?)
            ?.whereType<String>()
            .toList(growable: false) ??
        const [];
    final mode = (analysis['mode'] as String?) ?? '';
    final title =
        mode == 'screenshot_ocr' ? 'Screenshot text' : 'Image risk signals';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 16),
        Text(title, style: Theme.of(context).textTheme.titleMedium),
        if (mode == 'screenshot_ocr') ...[
          const SizedBox(height: 6),
          Text('OCR confidence: ${_percent(analysis['ocr_confidence'])}'),
        ],
        if (ocrText.isNotEmpty) ...[
          const SizedBox(height: 8),
          SelectableText(ocrText),
        ],
        if (reasons.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text('Reasons: ${reasons.take(4).join(', ')}'),
        ],
        if (warnings.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text('Warnings: ${warnings.take(4).join(', ')}'),
        ],
      ],
    );
  }
}

class _MetricChip extends StatelessWidget {
  const _MetricChip({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Chip(
      label: Text('$label $value'),
      visualDensity: VisualDensity.compact,
    );
  }
}

List<String> _stringList(dynamic value) {
  if (value is! List) {
    return const [];
  }
  return value.whereType<String>().toList(growable: false);
}

String _percent(dynamic value) {
  final number = _asDouble(value).clamp(0, 1).toDouble();
  return '${(number * 100).toStringAsFixed(0)}%';
}

double _asDouble(dynamic value) {
  if (value is num) {
    return value.toDouble();
  }
  if (value is String) {
    return double.tryParse(value) ?? 0;
  }
  return 0;
}

class EvidenceSection extends StatelessWidget {
  const EvidenceSection({super.key, required this.evidence});

  final List<Map<String, dynamic>> evidence;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 16),
        Text('Evidence', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        for (final item in evidence)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Text(
              [
                if (item['title'] case final String title when title.isNotEmpty)
                  title,
                if (item['domain'] case final String domain
                    when domain.isNotEmpty)
                  domain,
                if (item['stance'] case final String stance
                    when stance.isNotEmpty)
                  stance,
              ].join(' | '),
            ),
          ),
      ],
    );
  }
}

class VerificationMode {
  const VerificationMode({
    required this.label,
    required this.icon,
    required this.selectedIcon,
    required this.color,
    required this.child,
  });

  final String label;
  final IconData icon;
  final IconData selectedIcon;
  final Color color;
  final Widget child;
}

enum ImageSlot { screenshot, image }

class PickedImage {
  const PickedImage({required this.name, required this.bytes});

  final String name;
  final Uint8List bytes;
}

class AppTheme {
  static ThemeData get theme {
    final colorScheme = ColorScheme.fromSeed(
      seedColor: const Color(0xffa95f3d),
      brightness: Brightness.light,
    );
    return ThemeData(
      useMaterial3: true,
      colorScheme: colorScheme.copyWith(
        surface: const Color(0xfffffaf4),
        primary: const Color(0xffa95f3d),
        secondary: const Color(0xff2e6f64),
      ),
      scaffoldBackgroundColor: const Color(0xfff6eee5),
      appBarTheme: const AppBarTheme(
        backgroundColor: Color(0xfffffaf4),
        foregroundColor: Color(0xff18202f),
      ),
      cardTheme: CardThemeData(
        color: const Color(0xfffffaf4),
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(8),
          side: const BorderSide(color: Color(0xffe3d4c2)),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0xfffffcf7),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size.fromHeight(50),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size.fromHeight(50),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
      ),
      navigationBarTheme: const NavigationBarThemeData(
        backgroundColor: Color(0xfffffaf4),
        indicatorColor: Color(0xffffe5d2),
      ),
    );
  }
}
