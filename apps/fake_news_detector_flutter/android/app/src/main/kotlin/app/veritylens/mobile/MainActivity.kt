package app.veritylens.mobile

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val channelName = "app.veritylens.mobile/original_image_picker"
    private val pickOriginalImageRequest = 4201
    private val mediaLocationPermissionRequest = 4202

    private var pendingPickResult: MethodChannel.Result? = null
    private var launchPickerAfterPermission = false

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName).setMethodCallHandler { call, result ->
            when (call.method) {
                "pickOriginalImage" -> pickOriginalImage(result)
                else -> result.notImplemented()
            }
        }
    }

    private fun pickOriginalImage(result: MethodChannel.Result) {
        if (pendingPickResult != null) {
            result.error("busy", "An image picker is already open.", null)
            return
        }
        pendingPickResult = result
        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
            checkSelfPermission(Manifest.permission.ACCESS_MEDIA_LOCATION) != PackageManager.PERMISSION_GRANTED
        ) {
            launchPickerAfterPermission = true
            requestPermissions(
                arrayOf(Manifest.permission.ACCESS_MEDIA_LOCATION),
                mediaLocationPermissionRequest
            )
            return
        }
        launchOriginalImagePicker()
    }

    private fun launchOriginalImagePicker() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "image/*"
            putExtra(
                Intent.EXTRA_MIME_TYPES,
                arrayOf("image/jpeg", "image/png", "image/webp", "image/bmp", "image/tiff")
            )
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        }

        try {
            startActivityForResult(intent, pickOriginalImageRequest)
        } catch (_: ActivityNotFoundException) {
            val fallback = Intent(Intent.ACTION_GET_CONTENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "image/*"
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivityForResult(fallback, pickOriginalImageRequest)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == mediaLocationPermissionRequest && launchPickerAfterPermission) {
            launchPickerAfterPermission = false
            launchOriginalImagePicker()
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode != pickOriginalImageRequest) {
            super.onActivityResult(requestCode, resultCode, data)
            return
        }

        if (resultCode != Activity.RESULT_OK || data?.data == null) {
            completePick(null)
            return
        }

        val uri = data.data!!
        try {
            if ((data.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION) != 0) {
                try {
                    contentResolver.takePersistableUriPermission(
                        uri,
                        Intent.FLAG_GRANT_READ_URI_PERMISSION
                    )
                } catch (_: SecurityException) {
                    // Some providers grant temporary access only, which is enough for this read.
                }
            }

            val originalUri = originalMediaUri(uri)
            val bytes = readUriBytes(originalUri) ?: readUriBytes(uri)
            if (bytes == null) {
                completePickError("read_failed", "Could not read the selected image.")
                return
            }

            completePick(
                mapOf(
                    "name" to displayName(uri),
                    "bytes" to bytes,
                    "mimeType" to (contentResolver.getType(uri) ?: ""),
                    "usedOriginalUri" to (originalUri != uri)
                )
            )
        } catch (error: Exception) {
            completePickError("pick_failed", error.message ?: "Could not open the selected image.")
        }
    }

    private fun originalMediaUri(uri: Uri): Uri {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            return uri
        }
        return try {
            MediaStore.setRequireOriginal(uri)
        } catch (_: SecurityException) {
            uri
        } catch (_: IllegalArgumentException) {
            uri
        }
    }

    private fun readUriBytes(uri: Uri): ByteArray? {
        return contentResolver.openInputStream(uri)?.use { input -> input.readBytes() }
    }

    private fun displayName(uri: Uri): String {
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (nameIndex >= 0 && cursor.moveToFirst()) {
                val name = cursor.getString(nameIndex)
                if (!name.isNullOrBlank()) {
                    return name
                }
            }
        }

        val mimeType = contentResolver.getType(uri)
        val extension = MimeTypeMap.getSingleton().getExtensionFromMimeType(mimeType) ?: "jpg"
        return "original_image.$extension"
    }

    private fun completePick(value: Any?) {
        pendingPickResult?.success(value)
        pendingPickResult = null
    }

    private fun completePickError(code: String, message: String) {
        pendingPickResult?.error(code, message, null)
        pendingPickResult = null
    }
}
