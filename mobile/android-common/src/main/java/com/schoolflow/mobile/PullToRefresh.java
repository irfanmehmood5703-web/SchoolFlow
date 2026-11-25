package com.schoolflow.mobile;

import android.view.MotionEvent;
import android.view.View;
import android.widget.FrameLayout;

import java.util.function.BooleanSupplier;

/** Refresh a screen when a deliberate downward swipe starts and ends at its top. */
public final class PullToRefresh extends FrameLayout {
    private final View content;
    private final BooleanSupplier enabled;
    private final Runnable refresh;
    private final float distance;
    private boolean tracking;
    private float startX;
    private float startY;

    public PullToRefresh(View content, BooleanSupplier enabled, Runnable refresh) {
        super(content.getContext());
        this.content = content;
        this.enabled = enabled;
        this.refresh = refresh;
        distance = 64 * getResources().getDisplayMetrics().density;
        addView(content, new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));
    }

    @Override public boolean dispatchTouchEvent(MotionEvent event) {
        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                tracking = canRefresh();
                startX = event.getX();
                startY = event.getY();
                break;
            case MotionEvent.ACTION_POINTER_DOWN:
            case MotionEvent.ACTION_CANCEL:
                tracking = false;
                break;
            case MotionEvent.ACTION_UP:
                float down = event.getY() - startY;
                float across = Math.abs(event.getX() - startX);
                boolean swiped = tracking && down >= distance && down >= across * 1.5f && canRefresh();
                tracking = false;
                if (swiped) {
                    MotionEvent cancel = MotionEvent.obtain(event);
                    cancel.setAction(MotionEvent.ACTION_CANCEL);
                    super.dispatchTouchEvent(cancel);
                    cancel.recycle();
                    refresh.run();
                    return true;
                }
                break;
        }
        // Keep receiving the gesture even if it started on a blank, non-clickable part of the screen.
        return super.dispatchTouchEvent(event) || tracking;
    }

    private boolean canRefresh() {
        return enabled.getAsBoolean() && !content.canScrollVertically(-1);
    }
}
