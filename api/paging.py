from flask import request

MAX_PER_PAGE = 100


def paginate(query, default=25):
    """Apply ?page=&per_page= and return {items, total, page, pages, per_page} with raw rows in items."""
    try:
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(MAX_PER_PAGE, max(1, int(request.args.get('per_page', default))))
    except ValueError:
        page, per_page = 1, default
    total = query.count()
    rows = query.limit(per_page).offset((page - 1) * per_page).all()
    return {'rows': rows, 'total': total, 'page': page, 'per_page': per_page,
            'pages': max(1, -(-total // per_page))}
