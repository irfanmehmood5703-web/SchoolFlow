package com.schoolflow.mobile;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.graphics.drawable.Drawable;
import android.text.InputType;
import android.text.method.PasswordTransformationMethod;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageButton;
import android.widget.LinearLayout;

/** A masked credential field with an accessible, inline reveal button. */
public final class PasswordVisibility {
    private PasswordVisibility() {}

    public static boolean isPassword(int inputType) {
        int inputClass = inputType & InputType.TYPE_MASK_CLASS;
        int variation = inputType & InputType.TYPE_MASK_VARIATION;
        return (inputClass == InputType.TYPE_CLASS_TEXT &&
                (variation == InputType.TYPE_TEXT_VARIATION_PASSWORD ||
                 variation == InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD)) ||
               (inputClass == InputType.TYPE_CLASS_NUMBER &&
                variation == InputType.TYPE_NUMBER_VARIATION_PASSWORD);
    }

    private static int dp(Context context, int value) {
        return Math.round(value * context.getResources().getDisplayMetrics().density);
    }

    public static void addField(LinearLayout parent, EditText field, int color) {
        if (!isPassword(field.getInputType())) {
            parent.addView(field, new LinearLayout.LayoutParams(-1, -2));
            return;
        }
        Context context = field.getContext();
        int touch = dp(context, 48);
        field.setMinimumHeight(Math.max(touch, field.getMinimumHeight()));
        field.setPaddingRelative(field.getPaddingStart(), field.getPaddingTop(),
                field.getPaddingEnd() + touch, field.getPaddingBottom());
        field.setTransformationMethod(PasswordTransformationMethod.getInstance());
        field.setSaveEnabled(false);
        ImageButton button = new ImageButton(context);
        button.setPadding(dp(context, 12), dp(context, 12), dp(context, 12), dp(context, 12));
        button.setScaleType(android.widget.ImageView.ScaleType.FIT_CENTER);
        button.setFocusable(true);
        button.setSaveEnabled(false);
        TypedValue background = new TypedValue();
        if (context.getTheme().resolveAttribute(android.R.attr.selectableItemBackgroundBorderless, background, true)) {
            button.setBackgroundResource(background.resourceId);
        }
        Eye eye = new Eye(color);
        button.setImageDrawable(eye);
        // Keep the secure input type intact while only changing its transformation.
        Runnable hide = () -> setVisible(field, button, eye, false);
        FrameLayout row = new FrameLayout(context) {
            @Override public void onWindowFocusChanged(boolean focused) {
                super.onWindowFocusChanged(focused);
                if (!focused && eye.visible) hide.run();
            }
            @Override protected void onDetachedFromWindow() {
                if (eye.visible) hide.run();
                super.onDetachedFromWindow();
            }
        };
        row.addView(field, new FrameLayout.LayoutParams(-1, -2));
        row.addView(button, new FrameLayout.LayoutParams(touch, touch, Gravity.END | Gravity.CENTER_VERTICAL));
        button.setOnClickListener(v -> setVisible(field, button, eye, !eye.visible));
        hide.run();
        parent.addView(row, new LinearLayout.LayoutParams(-1, -2));
    }

    private static void setVisible(EditText field, ImageButton button, Eye eye, boolean visible) {
        int start = field.getSelectionStart(), end = field.getSelectionEnd();
        field.setTransformationMethod(visible ? null : PasswordTransformationMethod.getInstance());
        if (start >= 0 && end >= 0) field.setSelection(start, end);
        eye.visible = visible;
        eye.invalidateSelf();
        String label = visible ? "Hide password" : "Show password";
        button.setContentDescription(label);
        button.setTooltipText(label);
    }

    private static final class Eye extends Drawable {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        boolean visible;
        Eye(int color) {
            paint.setColor(color);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(1.7f);
            paint.setStrokeCap(Paint.Cap.ROUND);
            paint.setStrokeJoin(Paint.Join.ROUND);
        }
        @Override public void draw(Canvas canvas) {
            canvas.save();
            canvas.translate(getBounds().left, getBounds().top);
            canvas.scale(getBounds().width() / 24f, getBounds().height() / 24f);
            Path eye = new Path();
            eye.moveTo(2, 12);
            eye.cubicTo(7, 3, 17, 3, 22, 12);
            eye.cubicTo(17, 21, 7, 21, 2, 12);
            eye.close();
            canvas.drawPath(eye, paint);
            canvas.drawCircle(12, 12, 3, paint);
            if (visible) canvas.drawLine(4, 4, 20, 20, paint);
            canvas.restore();
        }
        @Override public void setAlpha(int alpha) { paint.setAlpha(alpha); invalidateSelf(); }
        @Override public void setColorFilter(ColorFilter filter) { paint.setColorFilter(filter); invalidateSelf(); }
        @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
        @Override public int getIntrinsicWidth() { return 24; }
        @Override public int getIntrinsicHeight() { return 24; }
    }
}
