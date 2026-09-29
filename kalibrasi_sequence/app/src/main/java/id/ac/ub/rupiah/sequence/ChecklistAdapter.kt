package id.ac.ub.rupiah.sequence

import android.view.LayoutInflater
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView

class ChecklistAdapter(
    private val onClick: (SequenceItem) -> Unit
) : RecyclerView.Adapter<ChecklistAdapter.Holder>() {
    private val items = mutableListOf<SequenceItem>()

    fun submit(newItems: List<SequenceItem>) {
        items.clear()
        items.addAll(newItems)
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.row_sequence, parent, false)
        return Holder(view as TextView)
    }

    override fun onBindViewHolder(holder: Holder, position: Int) {
        val item = items[position]
        holder.text.text = buildString {
            append(item.id)
            append("  •  ")
            append(item.displayName)
            append("\n")
            append(item.status)
            append(" / ")
            append(item.syncStatus)
        }
        holder.text.setOnClickListener { onClick(item) }
    }

    override fun getItemCount(): Int = items.size

    class Holder(val text: TextView) : RecyclerView.ViewHolder(text)
}
