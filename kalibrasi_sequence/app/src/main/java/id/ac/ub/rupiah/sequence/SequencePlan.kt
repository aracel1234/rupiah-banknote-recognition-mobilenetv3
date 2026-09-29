package id.ac.ub.rupiah.sequence

enum class SequenceKind { NOMINAL, NONUANG, TRANSITION }

data class StageSpec(
    val id: String,
    val title: String,
    val cue: String,
    val durationMs: Long,
    val expectedLabel: String?,
    val analysisRole: String
)

data class SequenceItem(
    val id: String,
    val kind: SequenceKind,
    val primaryLabel: String? = null,
    val secondaryLabel: String? = null,
    val scenario: String,
    val displayName: String,
    val stages: List<StageSpec>,
    var status: String = "PENDING",
    var savedAtIso: String? = null,
    var syncStatus: String = "NOT_SAVED"
) {
    val totalDurationMs: Long get() = stages.sumOf { it.durationMs }

    fun stageAt(elapsedMs: Long): StageSpec {
        var cursor = 0L
        for (stage in stages) {
            val end = cursor + stage.durationMs
            if (elapsedMs < end) return stage
            cursor = end
        }
        return stages.last()
    }

    fun stageStartMs(stageId: String): Long {
        var cursor = 0L
        for (stage in stages) {
            if (stage.id == stageId) return cursor
            cursor += stage.durationMs
        }
        return 0L
    }
}

object SequencePlan {
    val nominalLabels = listOf("1000", "2000", "5000", "10000", "20000", "50000", "100000")
    val classLabels = nominalLabels + "nonuang"

    private fun displayNominal(label: String): String = when (label) {
        "1000" -> "Rp1.000"
        "2000" -> "Rp2.000"
        "5000" -> "Rp5.000"
        "10000" -> "Rp10.000"
        "20000" -> "Rp20.000"
        "50000" -> "Rp50.000"
        "100000" -> "Rp100.000"
        else -> "Nonuang"
    }

    private fun commonNominalStages(label: String, actionTitle: String, actionCue: String): List<StageSpec> = listOf(
        StageSpec(
            id = "prepare_empty",
            title = "ROI kosong",
            cue = "Kosongkan ROI dan bersiap memasukkan ${displayNominal(label)}.",
            durationMs = 2_000,
            expectedLabel = "nonuang",
            analysisRole = "reset"
        ),
        StageSpec(
            id = "baseline",
            title = "Posisi awal",
            cue = "Tahan ${displayNominal(label)} stabil pada posisi awal.",
            durationMs = 2_500,
            expectedLabel = label,
            analysisRole = "target"
        ),
        StageSpec(
            id = "action",
            title = actionTitle,
            cue = actionCue,
            durationMs = 3_000,
            expectedLabel = label,
            analysisRole = "target"
        ),
        StageSpec(
            id = "recover",
            title = "Stabil kembali",
            cue = "Kembalikan ${displayNominal(label)} ke posisi stabil.",
            durationMs = 2_500,
            expectedLabel = label,
            analysisRole = "target"
        ),
        StageSpec(
            id = "remove",
            title = "Keluarkan objek",
            cue = "Keluarkan uang dari ROI sampai area kembali kosong.",
            durationMs = 2_000,
            expectedLabel = "nonuang",
            analysisRole = "reset"
        )
    )

    private fun nominalItem(label: String, scenario: String): SequenceItem {
        val (title, cue) = when (scenario) {
            "stable" -> "Tetap stabil" to "Pertahankan uang tetap diam dan seluruhnya berada di ROI."
            "motion" -> "Gerakan ringan" to "Gerakkan uang perlahan kiri-kanan tanpa keluar dari ROI."
            "distance" -> "Perubahan jarak" to "Ubah jarak secara perlahan 20 cm ke 10 cm, ke 30 cm, lalu kembali sekitar 20 cm."
            "orientation" -> "Perubahan orientasi" to "Miringkan uang secara ringan lalu kembalikan ke orientasi awal."
            else -> error("Skenario nominal tidak dikenal: $scenario")
        }
        val code = when (scenario) {
            "stable" -> "STABLE"
            "motion" -> "MOTION"
            "distance" -> "DISTANCE"
            else -> "ORIENTATION"
        }
        return SequenceItem(
            id = "NOM_${label}_$code",
            kind = SequenceKind.NOMINAL,
            primaryLabel = label,
            scenario = scenario,
            displayName = "${displayNominal(label)} • $title",
            stages = commonNominalStages(label, title, cue)
        )
    }

    private fun nonMoneyItem(index: Int, objectName: String): SequenceItem = SequenceItem(
        id = "NON_%02d".format(index),
        kind = SequenceKind.NONUANG,
        primaryLabel = "nonuang",
        scenario = objectName,
        displayName = "Nonuang %02d • $objectName".format(index),
        stages = listOf(
            StageSpec("prepare_empty", "ROI kosong", "Kosongkan ROI dan siapkan objek nonuang.", 2_000, "nonuang", "reset"),
            StageSpec("nonmoney", "Objek nonuang", "Tempatkan $objectName di pusat ROI dan pertahankan terlihat.", 8_000, "nonuang", "nonmoney"),
            StageSpec("remove", "Keluarkan objek", "Keluarkan objek sampai ROI kembali kosong.", 2_000, "nonuang", "reset")
        )
    )

    private fun transitionItem(
        index: Int,
        from: String,
        via: String,
        to: String
    ): SequenceItem {
        val middle = when (via) {
            "empty" -> StageSpec(
                "middle",
                "ROI kosong",
                "Keluarkan ${displayNominal(from)} sepenuhnya. Biarkan ROI kosong sebelum memasukkan ${displayNominal(to)}.",
                2_000,
                "nonuang",
                "reset"
            )
            "nonuang" -> StageSpec(
                "middle",
                "Objek nonuang",
                "Ganti ${displayNominal(from)} dengan satu objek nonuang, lalu bersiap memasukkan ${displayNominal(to)}.",
                2_000,
                "nonuang",
                "reset"
            )
            "direct" -> StageSpec(
                "middle",
                "Pergantian langsung",
                "Ganti ${displayNominal(from)} langsung menjadi ${displayNominal(to)} tanpa jeda kosong yang disengaja.",
                2_000,
                null,
                "transition"
            )
            else -> error("Jenis transisi tidak dikenal: $via")
        }
        return SequenceItem(
            id = "TR_%02d".format(index),
            kind = SequenceKind.TRANSITION,
            primaryLabel = from,
            secondaryLabel = to,
            scenario = via,
            displayName = "Transisi %02d • ${displayNominal(from)} → $via → ${displayNominal(to)}".format(index),
            stages = listOf(
                StageSpec("prepare_empty", "ROI kosong", "Kosongkan ROI dan siapkan ${displayNominal(from)}.", 2_000, "nonuang", "reset"),
                StageSpec("object_a", displayNominal(from), "Tahan ${displayNominal(from)} stabil di ROI.", 3_000, from, "target"),
                middle,
                StageSpec("object_b", displayNominal(to), "Tahan ${displayNominal(to)} stabil di ROI.", 3_000, to, "target"),
                StageSpec("remove", "Keluarkan objek", "Keluarkan objek sampai ROI kembali kosong.", 2_000, "nonuang", "reset")
            )
        )
    }

    fun build(): MutableList<SequenceItem> {
        val items = mutableListOf<SequenceItem>()
        for (label in nominalLabels) {
            items += nominalItem(label, "stable")
            items += nominalItem(label, "motion")
            items += nominalItem(label, "distance")
            items += nominalItem(label, "orientation")
        }

        val nonMoney = listOf(
            "dompet",
            "kartu plastik",
            "nota atau kertas",
            "telapak tangan",
            "kemasan produk",
            "latar kosong"
        )
        nonMoney.forEachIndexed { index, name -> items += nonMoneyItem(index + 1, name) }

        items += transitionItem(1, "1000", "empty", "2000")
        items += transitionItem(2, "5000", "empty", "10000")
        items += transitionItem(3, "20000", "empty", "50000")
        items += transitionItem(4, "100000", "direct", "1000")
        items += transitionItem(5, "50000", "nonuang", "20000")
        items += transitionItem(6, "10000", "direct", "100000")

        check(items.size == 40)
        check(items.count { it.kind == SequenceKind.NOMINAL } == 28)
        check(items.count { it.kind == SequenceKind.NONUANG } == 6)
        check(items.count { it.kind == SequenceKind.TRANSITION } == 6)
        check(items.map { it.id }.toSet().size == 40)
        check(items.all { it.totalDurationMs == 12_000L })
        return items
    }
}
