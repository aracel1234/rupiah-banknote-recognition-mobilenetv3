package id.ac.ub.rupiah.inference

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import org.tensorflow.lite.DataType
import org.tensorflow.lite.Interpreter
import java.io.FileInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel
import java.security.MessageDigest

/** Created, invoked and closed ONLY on the session's single analysis executor. */
class ModelRunner(
    private val context: Context,
    threads: Int
) : AutoCloseable {

    private fun bytes(name: String) =
        context.assets
            .open("model/$name")
            .use {
                it.readBytes()
            }

    private fun json(name: String) =
        JSONObject(
            String(
                bytes(name),
                Charsets.UTF_8
            )
        )

    val labels: List<String>
    val hash: String
    private val interpreter: Interpreter

    val input: ByteBuffer =
        ByteBuffer
            .allocateDirect(
                224 * 224 * 3 * 4
            )
            .order(
                ByteOrder.nativeOrder()
            )

    private val output =
        Array(1) {
            FloatArray(8)
        }

    init {
        val integrity =
            json(
                "asset_integrity.json"
            )

        for (
        name in listOf(
            "model.tflite",
            "class_names.json",
            "tensor_contract.json",
            "model_identity.json",
            "selection_lock.json"
        )
        ) {
            check(
                sha256(
                    bytes(name)
                ) == integrity.getString(name)
            ) {
                "Integritas aset berubah: $name"
            }
        }

        val lock =
            json(
                "selection_lock.json"
            )

        val identity =
            json(
                "model_identity.json"
            )

        val contract =
            json(
                "tensor_contract.json"
            )

        hash =
            sha256(
                bytes(
                    "model.tflite"
                )
            )

        check(
            hash == lock.getString(
                "model_sha256"
            ) &&
                    hash == identity.getString(
                "sha256"
            ) &&
                    hash == contract.getString(
                "model_sha256"
            )
        )

        check(
            lock.getString(
                "selected_candidate"
            ) == "dynamic_range" &&
                    contract.getString(
                        "candidate"
                    ) == "dynamic_range"
        )

        check(
            sha256(
                bytes(
                    "class_names.json"
                )
            ) == lock.getString(
                "class_names_sha256"
            )
        )

        val names =
            JSONArray(
                String(
                    bytes(
                        "class_names.json"
                    ),
                    Charsets.UTF_8
                )
            )

        labels =
            List(
                names.length()
            ) {
                names.getString(it)
            }

        check(
            labels ==
                    listOf(
                        "1000",
                        "2000",
                        "5000",
                        "10000",
                        "20000",
                        "50000",
                        "100000",
                        "nonuang"
                    )
        )

        check(
            labels ==
                    List(
                        contract
                            .getJSONArray(
                                "class_names"
                            )
                            .length()
                    ) {
                        contract
                            .getJSONArray(
                                "class_names"
                            )
                            .getString(it)
                    }
        )

        val mapped =
            context.assets
                .openFd(
                    "model/model.tflite"
                )
                .use { fd ->
                    FileInputStream(
                        fd.fileDescriptor
                    ).use {
                        it.channel.map(
                            FileChannel.MapMode.READ_ONLY,
                            fd.startOffset,
                            fd.declaredLength
                        )
                    }
                }

        val instance =
            Interpreter(
                mapped,
                Interpreter.Options()
                    .setNumThreads(
                        threads
                    )
                    .setUseXNNPACK(
                        true
                    )
                    .setUseNNAPI(
                        false
                    )
            )

        try {
            instance.allocateTensors()

            check(
                instance.inputTensorCount == 1 &&
                        instance.outputTensorCount == 1
            )

            for (
            (prefix, tensor) in
            listOf(
                "input" to instance.getInputTensor(0),
                "output" to instance.getOutputTensor(0)
            )
            ) {
                val shape =
                    contract.getJSONArray(
                        "${prefix}_shape"
                    )

                check(
                    tensor.shape().contentEquals(
                        IntArray(
                            shape.length()
                        ) {
                            shape.getInt(it)
                        }
                    )
                )

                check(
                    tensor.dataType() ==
                            DataType.FLOAT32 &&
                            contract.getString(
                                "${prefix}_dtype"
                            ) == "float32"
                )

                val q =
                    contract.getJSONArray(
                        "${prefix}_quantization"
                    )

                check(
                    tensor
                        .quantizationParams()
                        .scale ==
                            q.getDouble(0)
                                .toFloat()
                )

                check(
                    tensor
                        .quantizationParams()
                        .zeroPoint ==
                            q.getInt(1)
                )
            }

            check(
                instance
                    .getInputTensor(0)
                    .shape()
                    .contentEquals(
                        intArrayOf(
                            1,
                            224,
                            224,
                            3
                        )
                    )
            )

            check(
                instance
                    .getOutputTensor(0)
                    .shape()
                    .contentEquals(
                        intArrayOf(
                            1,
                            8
                        )
                    )
            )
        } catch (e: Exception) {
            instance.close()
            throw e
        }

        interpreter =
            instance
    }

    fun run(): FloatArray {
        input.rewind()

        interpreter.run(
            input,
            output
        )

        val scores =
            output[0]

        check(
            scores.all {
                it.isFinite() &&
                        it in -0.001f..1.001f
            } &&
                    kotlin.math.abs(
                        scores.sum() - 1f
                    ) < 0.01f
        ) {
            "Skor model tidak valid"
        }

        // Already softmax probabilities. Never normalize RGB or apply softmax again.
        return scores
    }

    override fun close() =
        interpreter.close()

    companion object {
        fun sha256(bytes: ByteArray) =
            MessageDigest
                .getInstance(
                    "SHA-256"
                )
                .digest(bytes)
                .joinToString("") {
                    "%02x".format(
                        it.toInt() and 255
                    )
                }
    }
}