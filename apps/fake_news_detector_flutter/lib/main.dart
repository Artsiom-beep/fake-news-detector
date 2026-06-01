import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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
  final _knowledgeSubjectController = TextEditingController();
  final _knowledgePropertyController = TextEditingController();

  int _selectedIndex = 0;
  bool _isLoading = false;
  bool _knowledgeTruth = true;
  String? _error;
  String? _knowledgeMessage;
  FactCheckResult? _result;
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
    _knowledgeSubjectController.dispose();
    _knowledgePropertyController.dispose();
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

  Future<void> _pickImage() async {
    final image = !kIsWeb && defaultTargetPlatform == TargetPlatform.android
        ? await AndroidOriginalImagePicker.pickImage()
        : await _pickImageWithFilePicker();
    if (image == null) {
      return;
    }

    setState(() {
      _error = null;
      _image = image;
    });
  }

  Future<PickedImage?> _pickImageWithFilePicker() async {
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.image,
      withData: true,
    );
    final file = picked?.files.single;
    if (file == null || file.bytes == null) {
      return null;
    }
    return PickedImage(
      name: file.name,
      bytes: file.bytes!,
      mimeType: _mimeTypeFromName(file.name),
      source: 'flutter_file_picker',
      mediaContext: {
        'source': 'flutter_file_picker',
        'sizeBytes': file.size,
        if ((file.extension ?? '').isNotEmpty) 'extension': file.extension,
      },
    );
  }

  Future<void> _pickLatestCameraImage() async {
    try {
      final image = await AndroidOriginalImagePicker.pickLatestCameraImage();
      if (!mounted || image == null) {
        return;
      }
      setState(() {
        _error = null;
        _image = image;
      });
    } on PlatformException catch (error) {
      if (!mounted) {
        return;
      }
      setState(() =>
          _error = error.message ?? 'Could not load the latest camera photo.');
    }
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

  Future<void> _addKnowledgeFact() async {
    final subject = _knowledgeSubjectController.text.trim();
    final propertyText = _knowledgePropertyController.text.trim();
    if (subject.isEmpty || propertyText.isEmpty) {
      setState(() => _error = 'Enter a subject and a property first.');
      return;
    }
    setState(() {
      _isLoading = true;
      _error = null;
      _knowledgeMessage = null;
    });
    try {
      final added = await widget.gateway.addKnowledgeFact(
        subject: subject,
        propertyText: propertyText,
        truth: _knowledgeTruth,
      );
      if (!mounted) {
        return;
      }
      setState(() {
        _knowledgeMessage =
            'Saved: ${added.subject} is ${added.truth ? '' : 'not '}${added.propertyText}';
        _factController.text =
            '${added.subject} is ${added.truth ? '' : 'not '}${added.propertyText}';
        _knowledgeSubjectController.clear();
        _knowledgePropertyController.clear();
        _result = null;
      });
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
          'The fact could not be saved. Verify the API URL and internet connection.');
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
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
        metadataContext: image.metadataContext,
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
          knowledgeSubjectController: _knowledgeSubjectController,
          knowledgePropertyController: _knowledgePropertyController,
          knowledgeTruth: _knowledgeTruth,
          onKnowledgeTruthChanged: (value) =>
              setState(() => _knowledgeTruth = value),
          knowledgeMessage: _knowledgeMessage,
          onSubmit: _checkFact,
          onAddKnowledgeFact: () => unawaited(_addKnowledgeFact()),
          isLoading: _isLoading,
        ),
      ),
      VerificationMode(
        label: 'Images',
        icon: Icons.image_search_outlined,
        selectedIcon: Icons.image_search,
        color: const Color(0xff8d4d6f),
        child: ImagePanel(
          title: 'Image metadata',
          selectedImage: _image,
          pickLabel: !kIsWeb && defaultTargetPlatform == TargetPlatform.android
              ? 'Choose file'
              : 'Open image file',
          actionLabel: 'Check metadata',
          onPick: _pickImage,
          onPickLatestCamera:
              !kIsWeb && defaultTargetPlatform == TargetPlatform.android
                  ? _pickLatestCameraImage
                  : null,
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
    required this.knowledgeSubjectController,
    required this.knowledgePropertyController,
    required this.knowledgeTruth,
    required this.onKnowledgeTruthChanged,
    required this.knowledgeMessage,
    required this.onSubmit,
    required this.onAddKnowledgeFact,
    required this.isLoading,
  });

  final TextEditingController controller;
  final TextEditingController knowledgeSubjectController;
  final TextEditingController knowledgePropertyController;
  final bool knowledgeTruth;
  final ValueChanged<bool> onKnowledgeTruthChanged;
  final String? knowledgeMessage;
  final VoidCallback onSubmit;
  final VoidCallback onAddKnowledgeFact;
  final bool isLoading;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        FormSurface(
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
        ),
        const SizedBox(height: 12),
        Card(
          child: ExpansionTile(
            leading: const Icon(Icons.library_books_outlined),
            title: Text(
              'Knowledge base',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w800,
                  ),
            ),
            childrenPadding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
            children: [
              AppTextField(
                controller: knowledgeSubjectController,
                label: 'Subject',
                textInputAction: TextInputAction.next,
              ),
              const SizedBox(height: 12),
              AppTextField(
                controller: knowledgePropertyController,
                label: 'Property',
                textInputAction: TextInputAction.done,
              ),
              const SizedBox(height: 12),
              SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(
                    value: true,
                    label: Text('True'),
                    icon: Icon(Icons.check_circle_outline),
                  ),
                  ButtonSegment(
                    value: false,
                    label: Text('False'),
                    icon: Icon(Icons.cancel_outlined),
                  ),
                ],
                selected: {knowledgeTruth},
                onSelectionChanged: isLoading
                    ? null
                    : (values) => onKnowledgeTruthChanged(values.first),
              ),
              if (knowledgeMessage != null) ...[
                const SizedBox(height: 12),
                KnowledgeMessage(knowledgeMessage!),
              ],
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: isLoading ? null : onAddKnowledgeFact,
                icon: const Icon(Icons.library_add_check_outlined),
                label: const Text('Add fact'),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class ImagePanel extends StatelessWidget {
  const ImagePanel({
    super.key,
    required this.title,
    required this.selectedImage,
    required this.pickLabel,
    required this.actionLabel,
    required this.onPick,
    this.onPickLatestCamera,
    required this.onSubmit,
    required this.isLoading,
  });

  final String title;
  final PickedImage? selectedImage;
  final String pickLabel;
  final String actionLabel;
  final VoidCallback onPick;
  final VoidCallback? onPickLatestCamera;
  final VoidCallback onSubmit;
  final bool isLoading;

  @override
  Widget build(BuildContext context) {
    return FormSurface(
      children: [
        OutlinedButton.icon(
          onPressed: isLoading ? null : onPick,
          icon: const Icon(Icons.upload_file),
          label: Text(
            selectedImage?.name ?? pickLabel,
            overflow: TextOverflow.ellipsis,
          ),
        ),
        if (onPickLatestCamera != null)
          OutlinedButton.icon(
            onPressed: isLoading ? null : onPickLatestCamera,
            icon: const Icon(Icons.photo_camera_back_outlined),
            label: const Text('Latest camera photo'),
          ),
        if (selectedImage != null)
          ImagePreview(
            title: title,
            image: selectedImage!,
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

class CameraOriginalPickerSheet extends StatelessWidget {
  const CameraOriginalPickerSheet({super.key, required this.items});

  final List<CameraImageItem> items;

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final crossAxisCount = width >= 620 ? 5 : (width >= 430 ? 4 : 3);
    return SafeArea(
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.72,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Camera originals',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 12),
              Expanded(
                child: GridView.builder(
                  itemCount: items.length,
                  gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                    crossAxisCount: crossAxisCount,
                    crossAxisSpacing: 10,
                    mainAxisSpacing: 10,
                    childAspectRatio: 0.72,
                  ),
                  itemBuilder: (context, index) {
                    return _CameraOriginalTile(item: items[index]);
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CameraOriginalTile extends StatelessWidget {
  const _CameraOriginalTile({required this.item});

  final CameraImageItem item;

  @override
  Widget build(BuildContext context) {
    final details = [
      item.dateLabel,
      item.sizeLabel,
      item.dimensionsLabel,
    ].where((value) => value.isNotEmpty).join(' | ');
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: () => Navigator.of(context).pop(item),
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xffe3d4c2)),
          color: const Color(0xfffffcf7),
        ),
        clipBehavior: Clip.antiAlias,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              child: item.thumbnail == null
                  ? const ColoredBox(
                      color: Color(0xfff2e8dc),
                      child: Icon(Icons.image_outlined, size: 34),
                    )
                  : Image.memory(
                      item.thumbnail!,
                      fit: BoxFit.cover,
                      gaplessPlayback: true,
                    ),
            ),
            Padding(
              padding: const EdgeInsets.all(8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context)
                        .textTheme
                        .labelMedium
                        ?.copyWith(fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    details,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.labelSmall,
                  ),
                ],
              ),
            ),
          ],
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

class KnowledgeMessage extends StatelessWidget {
  const KnowledgeMessage(this.message, {super.key});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xffdff4e7),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xffa7d7b9)),
      ),
      child: Text(
        message,
        style: const TextStyle(
          color: Color(0xff146c48),
          fontWeight: FontWeight.w700,
        ),
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
    final friendlyReasons =
        mode == 'screenshot_ocr' ? reasons : _friendlyImageSignals(reasons);
    final friendlyWarnings =
        mode == 'screenshot_ocr' ? warnings : _friendlyImageSignals(warnings);
    final reasonLabel =
        mode == 'screenshot_ocr' ? 'Reasons' : 'Metadata signals';
    final warningLabel = mode == 'screenshot_ocr' ? 'Warnings' : 'Limits';
    final title =
        mode == 'screenshot_ocr' ? 'Screenshot text' : 'Image metadata';
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
        if (friendlyReasons.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text('$reasonLabel: ${friendlyReasons.take(4).join(', ')}'),
        ],
        if (friendlyWarnings.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text('$warningLabel: ${friendlyWarnings.take(4).join(', ')}'),
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

String _friendlyImageSignal(String value) {
  if (value.startsWith('ai_metadata_marker=')) {
    return 'Generator metadata was found.';
  }
  if (value.startsWith('ai_filename_marker=')) {
    return 'The filename mentions an AI generator.';
  }
  if (value.startsWith('camera_metadata_present=')) {
    return 'Original camera metadata is present.';
  }
  if (value == 'android_camera_library_context') {
    return 'Android says this file came from the camera library.';
  }
  if (value.startsWith('android_camera_source=')) {
    return 'Selected through the phone camera source.';
  }
  if (value == 'media_store_date_taken_present') {
    return 'The phone library has a camera date for this image.';
  }
  if (value.startsWith('media_store_dimensions=')) {
    return 'The phone library has image dimensions for this file.';
  }
  if (value == 'media_store_original_uri_used') {
    return 'Android allowed reading the original media file.';
  }
  if (value == 'metadata_context_not_camera_origin') {
    return 'The selected file was not confirmed as a camera original.';
  }
  if (value == 'camera_context_not_proof') {
    return 'Phone library context supports camera origin, but it is not proof.';
  }
  if (value.startsWith('common_square_ai_dimension=')) {
    return 'The image uses a common square generation size.';
  }
  if (value.startsWith('generator_friendly_dimensions=')) {
    return 'The dimensions are common for generated or exported images.';
  }
  if (value == 'android_exported_jpeg_without_camera_metadata') {
    return 'The file looks exported or shared and has no original camera EXIF.';
  }
  if (value == 'optional_ai_image_model_disabled') {
    return 'The free cloud backend is using lightweight metadata analysis.';
  }
  if (value == 'camera_metadata_missing_not_proof') {
    return 'No original camera metadata was found.';
  }
  if (value == 'image_may_be_exported_or_shared_not_original_camera') {
    return 'The file may be exported, shared, downloaded, or stripped.';
  }
  if (value == 'limited_metadata_only_ai_check') {
    return 'This cloud check reads metadata, not the full visual content.';
  }
  if (value == 'ai_image_detection_not_definitive') {
    return 'Metadata is useful context, not proof.';
  }
  if (value.startsWith('model_')) {
    return 'Optional visual model signal: $value';
  }
  return value.replaceAll('_', ' ');
}

List<String> _friendlyImageSignals(List<String> values) {
  final seen = <String>{};
  final friendly = <String>[];
  for (final value in values) {
    final mapped = _friendlyImageSignal(value);
    if (seen.add(mapped)) {
      friendly.add(mapped);
    }
  }
  return friendly;
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

class CameraImageItem {
  const CameraImageItem({
    required this.id,
    required this.name,
    required this.mimeType,
    required this.dateTaken,
    required this.dateAdded,
    required this.sizeBytes,
    required this.width,
    required this.height,
    required this.relativePath,
    required this.bucketName,
    required this.thumbnail,
  });

  final int id;
  final String name;
  final String mimeType;
  final int dateTaken;
  final int dateAdded;
  final int sizeBytes;
  final int width;
  final int height;
  final String relativePath;
  final String bucketName;
  final Uint8List? thumbnail;

  String get dateLabel =>
      _formatPhotoDate(dateTaken > 0 ? dateTaken : dateAdded * 1000);
  String get sizeLabel => _formatFileSize(sizeBytes);
  String get dimensionsLabel =>
      width > 0 && height > 0 ? '${width}x$height' : '';

  factory CameraImageItem.fromMap(Map<dynamic, dynamic> map) {
    return CameraImageItem(
      id: _asInt(map['id']),
      name: (map['name'] as String?)?.trim().isNotEmpty == true
          ? map['name'] as String
          : 'camera_original.jpg',
      mimeType: (map['mimeType'] as String?) ?? 'image/jpeg',
      dateTaken: _asInt(map['dateTaken']),
      dateAdded: _asInt(map['dateAdded']),
      sizeBytes: _asInt(map['sizeBytes']),
      width: _asInt(map['width']),
      height: _asInt(map['height']),
      relativePath: (map['relativePath'] as String?) ?? '',
      bucketName: (map['bucketName'] as String?) ?? '',
      thumbnail:
          map['thumbnail'] is Uint8List ? map['thumbnail'] as Uint8List : null,
    );
  }
}

class PickedImage {
  const PickedImage({
    required this.name,
    required this.bytes,
    this.mimeType = 'image/jpeg',
    this.source = '',
    this.usedOriginalUri = false,
    this.mediaContext = const <String, dynamic>{},
  });

  final String name;
  final Uint8List bytes;
  final String mimeType;
  final String source;
  final bool usedOriginalUri;
  final Map<String, dynamic> mediaContext;

  Map<String, dynamic> get metadataContext {
    final context = <String, dynamic>{...mediaContext};
    context['filename'] = name;
    if (mimeType.trim().isNotEmpty) {
      context['mimeType'] = mimeType;
    }
    if (source.trim().isNotEmpty) {
      context['source'] = source;
    }
    context['usedOriginalUri'] = usedOriginalUri;
    return context;
  }
}

int _asInt(dynamic value) {
  if (value is int) {
    return value;
  }
  if (value is num) {
    return value.toInt();
  }
  if (value is String) {
    return int.tryParse(value) ?? 0;
  }
  return 0;
}

bool _asBool(dynamic value) {
  if (value is bool) {
    return value;
  }
  if (value is num) {
    return value != 0;
  }
  if (value is String) {
    final normalized = value.trim().toLowerCase();
    return normalized == 'true' || normalized == '1' || normalized == 'yes';
  }
  return false;
}

String _asString(dynamic value) {
  return value is String ? value.trim() : '';
}

Map<String, dynamic> _stringDynamicMap(dynamic value) {
  if (value is! Map) {
    return <String, dynamic>{};
  }
  final mapped = <String, dynamic>{};
  value.forEach((key, rawValue) {
    if (key == null || rawValue == null) {
      return;
    }
    if (rawValue is String || rawValue is num || rawValue is bool) {
      mapped[key.toString()] = rawValue;
    }
  });
  return mapped;
}

String _mimeTypeFromName(String filename) {
  final lower = filename.toLowerCase();
  if (lower.endsWith('.png')) {
    return 'image/png';
  }
  if (lower.endsWith('.webp')) {
    return 'image/webp';
  }
  if (lower.endsWith('.bmp')) {
    return 'image/bmp';
  }
  if (lower.endsWith('.tif') || lower.endsWith('.tiff')) {
    return 'image/tiff';
  }
  return 'image/jpeg';
}

String _formatPhotoDate(int millisecondsSinceEpoch) {
  if (millisecondsSinceEpoch <= 0) {
    return '';
  }
  final value =
      DateTime.fromMillisecondsSinceEpoch(millisecondsSinceEpoch).toLocal();
  String twoDigits(int number) => number.toString().padLeft(2, '0');
  return '${twoDigits(value.day)}.${twoDigits(value.month)} ${twoDigits(value.hour)}:${twoDigits(value.minute)}';
}

String _formatFileSize(int bytes) {
  if (bytes <= 0) {
    return '';
  }
  if (bytes < 1024) {
    return '$bytes B';
  }
  final kib = bytes / 1024;
  if (kib < 1024) {
    return '${kib.toStringAsFixed(kib >= 100 ? 0 : 1)} KB';
  }
  final mib = kib / 1024;
  return '${mib.toStringAsFixed(mib >= 100 ? 0 : 1)} MB';
}

class AndroidOriginalImagePicker {
  static const _channel =
      MethodChannel('app.veritylens.mobile/original_image_picker');

  static Future<PickedImage?> pickImage() async {
    final result = await _channel.invokeMapMethod<String, dynamic>(
      'pickOriginalImage',
    );
    return _pickedImageFromResult(result);
  }

  static Future<List<CameraImageItem>> listCameraImages({
    int limit = 80,
  }) async {
    final result = await _channel.invokeMethod<List<dynamic>>(
      'listCameraImages',
      {'limit': limit},
    );
    if (result == null) {
      return const [];
    }
    return [
      for (final item in result)
        if (item is Map) CameraImageItem.fromMap(item),
    ];
  }

  static Future<PickedImage?> loadCameraImage(int id) async {
    final result = await _channel.invokeMapMethod<String, dynamic>(
      'loadCameraImage',
      {'id': id},
    );
    return _pickedImageFromResult(result);
  }

  static Future<PickedImage?> pickLatestCameraImage() async {
    final result = await _channel.invokeMapMethod<String, dynamic>(
      'pickLatestCameraImage',
    );
    return _pickedImageFromResult(result);
  }

  static PickedImage? _pickedImageFromResult(Map<dynamic, dynamic>? result) {
    if (result == null) {
      return null;
    }
    final bytes = result['bytes'];
    final name = result['name'];
    if (bytes is! Uint8List || name is! String || name.trim().isEmpty) {
      return null;
    }
    final context = _stringDynamicMap(result['context']);
    final mimeType = _asString(result['mimeType']);
    final source = _asString(result['source']);
    final usedOriginalUri = _asBool(result['usedOriginalUri']);
    if (mimeType.isNotEmpty) {
      context['mimeType'] = mimeType;
    }
    if (source.isNotEmpty) {
      context['source'] = source;
    }
    context['usedOriginalUri'] = usedOriginalUri;
    return PickedImage(
      name: name,
      bytes: bytes,
      mimeType: mimeType.isNotEmpty ? mimeType : _mimeTypeFromName(name),
      source: source,
      usedOriginalUri: usedOriginalUri,
      mediaContext: context,
    );
  }
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
